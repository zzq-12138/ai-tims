package com.tims.ai.service;

import com.tims.ai.apikey.AiTenantContext;
import com.tims.ai.cache.CacheService;
import com.tims.ai.config.AiProperties;
import com.tims.ai.dto.ChatRequest;
import com.tims.ai.dto.ChatResponseVO;
import com.tims.ai.fallback.FallbackSuggestionService;
import com.tims.ai.guard.GuardService;
import com.tims.ai.llm.LlmException;
import com.tims.ai.llm.ZhipuStreamClient;
import com.tims.ai.observe.AiTrace;
import com.tims.ai.rag.KbRef;
import com.tims.ai.rag.RagService;
import com.tims.ai.route.ModelRouter;
import com.tims.ai.usage.AiCallLog;
import com.tims.ai.usage.AiUsageService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * RAG 问答编排：检索 → 拼 prompt → 流式/同步生成 → usage 落库 → 降级标注。
 */
@Service
public class ChatService {

    private static final Logger log = LoggerFactory.getLogger(ChatService.class);

    private final RagService ragService;
    private final ZhipuStreamClient streamClient;
    private final OpenAiChatModel chatModel;
    private final AiProperties props;
    private final AiUsageService usageService;
    private final GuardService guard;
    private final ModelRouter modelRouter;
    private final CacheService cache;
    private final FallbackSuggestionService fallbackSuggestion;

    public ChatService(RagService ragService, ZhipuStreamClient streamClient,
                       OpenAiChatModel chatModel, AiProperties props, AiUsageService usageService,
                       GuardService guard, ModelRouter modelRouter, CacheService cache,
                       FallbackSuggestionService fallbackSuggestion) {
        this.ragService = ragService;
        this.streamClient = streamClient;
        this.chatModel = chatModel;
        this.props = props;
        this.usageService = usageService;
        this.guard = guard;
        this.modelRouter = modelRouter;
        this.cache = cache;
        this.fallbackSuggestion = fallbackSuggestion;
    }

    /** 流式事件出口（控制器用 SseEmitter 实现） */
    public interface StreamSink {
        void meta(Map<String, Object> meta);
        void reasoning(String delta);
        void content(String delta);
        void usage(Map<String, Object> usage);
        void error(int code, String message);
        void done();
    }

    /** 同步问答（便于测试/降级兜底） */
    public ChatResponseVO chatSync(Long tenantId, ChatRequest request) {
        long t0 = System.currentTimeMillis();
        AiTrace.start();
        GuardService.Decision in = guard.inspectInput(request.getQuestion(), historyText(request));
        if (in.blocked()) {
            AiCallLog row = new AiCallLog();
            row.setTenantId(tenantId);
            row.setScene("CHAT_SYNC");
            row.setModel(props.getModel());
            row.setLatencyMs(System.currentTimeMillis() - t0);
            row.setStatus("BLOCKED");
            row.setDegraded(true);
            row.setGuardBlocked(true);
            row.setPromptVersion("guard-v1");
            row.setErrorMsg(truncate(String.join(",", in.reasons()), 250));
            useageRecord(row);
            throw new LlmException(40301, "请求被安全护栏拦截：" + String.join(",", in.reasons()));
        }
        RagService.RagContext ctx = ragService.prepare(tenantId, guard.maskRequest(request));
        boolean noKb = ctx.noKbBasis();
        GuardService.Decision ctxIn = guard.inspectInput(userPromptText(ctx));
        if (ctxIn.blocked()) {
            throw new LlmException(40302, "检索上下文命中注入特征：" + String.join(",", ctxIn.reasons()));
        }
        ModelRouter.Decision route = route(request, ctx);
        String model = route == null ? props.getModel() : route.model();
        String maskedQuestion = guard.mask(request.getQuestion());
        String scope = cacheScope(request, ctx);
        CacheService.Probe probe = probeCache(tenantId, maskedQuestion, scope, model, ctx);
        if (probe.isHit()) {
            ChatResponseVO vo = cacheHitResponse(probe.result(), model, route, in, ctx, t0);
            AiCallLog row = baseLog(tenantId, "CHAT_SYNC", ctx, vo.getLatencyMs(), model);
            row.setStatus("CACHE_HIT");
            row.setPromptTokens(0);
            row.setCompletionTokens(0);
            row.setTotalTokens(0);
            useageRecord(row);
            log.info("[ai] sync cache hit sim={} exact={} latency={}ms",
                    probe.result().similarity(), probe.result().exact(), vo.getLatencyMs());
            return vo;
        }
        try {
            ChatResponse resp;
            AiTenantContext.set(tenantId);
            try {
                resp = chatModel.call(new Prompt(toMessages(ctx.messages()),
                        OpenAiChatOptions.builder()
                                .model(model)
                                .maxTokens(props.getMaxTokens())
                                .temperature(props.getTemperature())
                                .build()));
            } finally {
                AiTenantContext.clear();
            }
            String answer = resp.getResult() == null ? "" : resp.getResult().getOutput().getText();
            GuardService.Filtered filtered = guard.filterOutput(answer);
            answer = filtered.text();
            if (!filtered.blocked() && !ctx.fallback() && !ctx.unavailable() && !noKb) {
                cache.put(tenantId, scope, model, probe, maskedQuestion, answer, ctx.refs());
            }
            Usage u = resp.getMetadata() == null ? null : resp.getMetadata().getUsage();
            int prompt = u == null || u.getPromptTokens() == null ? 0 : u.getPromptTokens();
            int completion = u == null || u.getCompletionTokens() == null ? 0 : u.getCompletionTokens();
            long total = System.currentTimeMillis() - t0;

            ChatResponseVO vo = new ChatResponseVO();
            String body = noKb ? FallbackSuggestionService.MARKER + "\n\n" + answer : answer;
            vo.setAnswer(ctx.degradedNote() == null ? body : ctx.degradedNote() + "\n\n" + body);
            vo.setModel(model);
            vo.setRefs(ctx.refs());
            vo.setFallback(ctx.fallback());
            vo.setDegraded(ctx.fallback() || filtered.blocked());
            vo.setDegradedNote(ctx.degradedNote());
            vo.setRetrievalMs(ctx.retrievalMs());
            vo.setLatencyMs(total);
            vo.setUsage(new ChatResponseVO.Usage(prompt, completion, prompt + completion));
            if (guard.enabled()) {
                vo.setGuard(guardMeta(in, filtered));
            }
            if (route != null) {
                vo.setRoute(routeMeta(route));
            }
            if (cache.enabled()) {
                vo.setCache(cacheMissMeta());
            }
            if (noKb) {
                vo.setTier("C");
                vo.setTierReason(ctx.tierReason());
                vo.setNoKbBasis(true);
                vo.setSuggestionId(fallbackSuggestion.record(
                        tenantId, ctx.ticketId(), ctx.ticketNo(), answer, ctx.promptVersion(), request.getSessionId()));
            }

            AiCallLog row = baseLog(tenantId, "CHAT_SYNC", ctx, total, model);
            row.setPromptTokens(prompt);
            row.setCompletionTokens(completion);
            row.setTotalTokens(prompt + completion);
            row.setStatus(filtered.blocked() ? "BLOCKED"
                    : (noKb ? "FALLBACK" : (ctx.fallback() ? "DEGRADED" : "SUCCESS")));
            row.setGuardBlocked(filtered.blocked());
            useageRecord(row);
            log.info("[ai] sync done model={} prompt={} completion={} total={}ms", model, prompt, completion, total);
            return vo;
        } catch (Exception e) {
            AiCallLog row = baseLog(tenantId, "CHAT_SYNC", ctx, System.currentTimeMillis() - t0, model);
            row.setStatus("ERROR");
            row.setErrorMsg(truncate(e.getMessage(), 250));
            useageRecord(row);
            log.error("[ai] sync failed: {}", e.getMessage());
            if (e instanceof LlmException le) {
                throw le;
            }
            throw new LlmException(40201, "AI 服务不可用：" + e.getMessage());
        }
    }

    /** 流式问答 */
    public void chatStream(Long tenantId, ChatRequest request, StreamSink sink) {
        long t0 = System.currentTimeMillis();
        AiTrace.start();
        GuardService.Decision in = guard.inspectInput(request.getQuestion(), historyText(request));
        if (in.blocked()) {
            Map<String, Object> meta = new LinkedHashMap<>();
            meta.put("model", props.getModel());
            meta.put("refs", List.of());
            meta.put("fallback", true);
            meta.put("unavailable", false);
            meta.put("mode", "GUARD");
            meta.put("retrievalMs", 0L);
            meta.put("degraded", true);
            meta.put("degradedNote", "请求命中安全护栏，未调用模型。");
            meta.put("guardBlocked", true);
            meta.put("guardReasons", in.reasons());
            sink.meta(meta);
            String reply = guard.props().getBlockReply();
            sink.content(reply + "\n\n");
            AiCallLog row = new AiCallLog();
            row.setTenantId(tenantId);
            row.setScene("CHAT_STREAM");
            row.setModel(props.getModel());
            row.setLatencyMs(System.currentTimeMillis() - t0);
            row.setStatus("BLOCKED");
            row.setDegraded(true);
            row.setGuardBlocked(true);
            row.setPromptVersion("guard-v1");
            row.setErrorMsg(truncate(String.join(",", in.reasons()), 250));
            useageRecord(row);
            Map<String, Object> usage = new LinkedHashMap<>();
            usage.put("guardBlocked", true);
            usage.put("latencyMs", System.currentTimeMillis() - t0);
            sink.usage(usage);
            sink.done();
            return;
        }
        RagService.RagContext ctx;
        try {
            ctx = ragService.prepare(tenantId, guard.maskRequest(request));
        } catch (Exception e) {
            sink.error(10400, e.getMessage());
            sink.done();
            return;
        }
        GuardService.Decision ctxIn = guard.inspectInput(userPromptText(ctx));
        if (ctxIn.blocked()) {
            sink.meta(Map.of("model", props.getModel(), "guardBlocked", true,
                    "guardReasons", ctxIn.reasons(), "degraded", true));
            sink.content(guard.props().getBlockReply() + "\n\n");
            sink.usage(Map.of("guardBlocked", true));
            AiCallLog row = new AiCallLog();
            row.setTenantId(tenantId);
            row.setScene("CHAT_STREAM");
            row.setModel(props.getModel());
            row.setLatencyMs(System.currentTimeMillis() - t0);
            row.setStatus("BLOCKED");
            row.setDegraded(true);
            row.setGuardBlocked(true);
            row.setPromptVersion(ctx.promptVersion());
            row.setErrorMsg(truncate(String.join(",", ctxIn.reasons()), 250));
            useageRecord(row);
            sink.done();
            return;
        }

        ModelRouter.Decision route = route(request, ctx);
        String model = route == null ? props.getModel() : route.model();
        String maskedQuestion = guard.mask(request.getQuestion());
        String scope = cacheScope(request, ctx);
        boolean noKb = ctx.noKbBasis();
        CacheService.Probe probe = probeCache(tenantId, maskedQuestion, scope, model, ctx);

        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("model", model);
        meta.put("refs", ctx.refs());
        meta.put("fallback", ctx.fallback());
        meta.put("unavailable", ctx.unavailable());
        meta.put("mode", ctx.mode());
        meta.put("retrievalMs", ctx.retrievalMs());
        meta.put("degraded", ctx.fallback() || ctx.unavailable());
        meta.put("degradedNote", ctx.degradedNote());
        if (guard.enabled()) {
            meta.put("guardEnabled", true);
        }
        if (route != null) {
            meta.put("route", routeMeta(route));
        }
        if (cache.enabled()) {
            meta.put("cache", probe.isHit() ? cacheMeta(probe.result()) : cacheMissMeta());
        }
        if (noKb) {
            meta.put("tier", "C");
            meta.put("tierReason", ctx.tierReason());
            meta.put("noKbBasis", true);
        }
        sink.meta(meta);

        if (probe.isHit()) {
            CacheService.Hit hit = probe.result();
            long total = System.currentTimeMillis() - t0;
            sink.content(hit.answer());
            Map<String, Object> usage = new LinkedHashMap<>();
            usage.put("model", model);
            usage.put("promptTokens", 0);
            usage.put("completionTokens", 0);
            usage.put("totalTokens", 0);
            usage.put("latencyMs", total);
            usage.put("cacheHit", true);
            usage.put("cacheSimilarity", hit.similarity());
            usage.put("degraded", false);
            usage.put("refs", ctx.refs().size());
            usage.put("guardBlocked", false);
            sink.usage(usage);
            AiCallLog row = baseLog(tenantId, "CHAT_STREAM", ctx, total, model);
            row.setStatus("CACHE_HIT");
            row.setPromptTokens(0);
            row.setCompletionTokens(0);
            row.setTotalTokens(0);
            useageRecord(row);
            log.info("[ai] stream cache hit sim={} exact={} latency={}ms",
                    hit.similarity(), hit.exact(), total);
            sink.done();
            return;
        }

        // 降级标注先落正文首段，保证“回答里标注”不依赖模型是否听话
        if (ctx.degradedNote() != null) {
            sink.content(ctx.degradedNote() + "\n\n");
        }
        // C 档兜底：统一由服务端加“无知识库依据”标记，前端与日志据此区分
        if (noKb) {
            sink.content(FallbackSuggestionService.MARKER + "\n\n");
        }

        GuardService.StreamFilter streamFilter = guard.newStreamFilter();
        StringBuilder acc = new StringBuilder();
        try {
            ZhipuStreamClient.StreamResult result = streamClient.stream(
                    tenantId, model, props.getMaxTokens(), props.getTemperature(), ctx.messages(),
                    new ZhipuStreamClient.Listener() {
                        @Override
                        public void onReasoning(String delta) {
                            sink.reasoning(delta);
                        }

                        @Override
                        public void onContent(String delta) {
                            String safe = streamFilter.accept(delta);
                            if (!safe.isEmpty()) {
                                acc.append(safe);
                                sink.content(safe);
                            }
                        }
                    });
            String tail = streamFilter.finish();
            if (!tail.isEmpty()) {
                acc.append(tail);
                sink.content(tail);
            }
            if (!streamFilter.blocked() && !ctx.fallback() && !ctx.unavailable() && !noKb) {
                cache.put(tenantId, scope, model, probe, maskedQuestion, acc.toString(), ctx.refs());
            }
            Long suggestionId = noKb
                    ? fallbackSuggestion.record(tenantId, ctx.ticketId(), ctx.ticketNo(),
                            acc.toString(), ctx.promptVersion(), request.getSessionId())
                    : null;

            AiCallLog row = baseLog(tenantId, "CHAT_STREAM", ctx, result.totalMs(), model);
            row.setPromptTokens((int) result.usage().promptTokens());
            row.setCompletionTokens((int) result.usage().completionTokens());
            row.setTotalTokens((int) result.usage().totalTokens());
            row.setReasoningTokens((int) result.usage().reasoningTokens());
            row.setFirstTokenMs(result.firstTokenMs());
            row.setStatus(streamFilter.blocked() ? "BLOCKED"
                    : (noKb ? "FALLBACK" : (ctx.fallback() ? "DEGRADED" : "SUCCESS")));
            row.setGuardBlocked(streamFilter.blocked());
            useageRecord(row);

            Map<String, Object> usage = new LinkedHashMap<>();
            usage.put("model", model);
            usage.put("promptTokens", result.usage().promptTokens());
            usage.put("completionTokens", result.usage().completionTokens());
            usage.put("totalTokens", result.usage().totalTokens());
            usage.put("reasoningTokens", result.usage().reasoningTokens());
            usage.put("latencyMs", result.totalMs());
            usage.put("firstTokenMs", result.firstTokenMs());
            usage.put("firstContentMs", result.firstContentMs());
            usage.put("reasoningChars", result.reasoningChars());
            usage.put("finishReason", result.finishReason());
            usage.put("degraded", ctx.fallback() || ctx.unavailable());
            usage.put("refs", ctx.refs().size());
            usage.put("guardBlocked", streamFilter.blocked());
            if (noKb) {
                usage.put("noKbBasis", true);
                // 雪花 ID 超出 JS Number 安全整数范围，必须按字符串下发，否则前端回填会精度丢失
                usage.put("fallbackSuggestionId", suggestionId == null ? null : String.valueOf(suggestionId));
            }
            sink.usage(usage);
            sink.done();
        } catch (LlmException e) {
            AiCallLog row = baseLog(tenantId, "CHAT_STREAM", ctx, System.currentTimeMillis() - t0, model);
            row.setStatus("ERROR");
            row.setErrorMsg(truncate(e.getMessage(), 250));
            useageRecord(row);
            log.error("[ai] stream failed code={} msg={}", e.getCode(), e.getMessage());
            sink.error(e.getCode(), e.getMessage());
            sink.done();
        } catch (Exception e) {
            AiCallLog row = baseLog(tenantId, "CHAT_STREAM", ctx, System.currentTimeMillis() - t0, model);
            row.setStatus("ERROR");
            row.setErrorMsg(truncate(e.getMessage(), 250));
            useageRecord(row);
            log.error("[ai] stream failed unexpected: {}", e.getMessage());
            sink.error(40201, "AI 服务不可用：" + e.getMessage());
            sink.done();
        }
    }

    /** 路由关闭时返回 null，调用方沿用 props.getModel()，行为与改动前一致 */
    private ModelRouter.Decision route(ChatRequest request, RagService.RagContext ctx) {
        AiProperties.Router cfg = props.getRouter();
        if (cfg == null || !cfg.isEnabled()) {
            return null;
        }
        int refs = ctx.refs() == null ? 0 : ctx.refs().size();
        return modelRouter.route(new ModelRouter.Input(request.getQuestion(),
                historyCount(request), needsTool(request.getQuestion()), refs));
    }

    private Map<String, Object> routeMeta(ModelRouter.Decision d) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("tier", d.simple() ? "simple" : "complex");
        m.put("model", d.model());
        m.put("score", d.score());
        m.put("reason", d.reason());
        return m;
    }

    /** 需要现查工单/设备的问题，工具调度交给大模型 */
    private boolean needsTool(String question) {
        if (question == null) {
            return false;
        }
        return question.contains("工单") || question.contains("设备编号") || question.contains("设备号")
                || question.contains("查一下") || question.contains("查询");
    }

    private int historyCount(ChatRequest request) {
        return request.getHistory() == null ? 0 : request.getHistory().size();
    }

    private String userPromptText(RagService.RagContext ctx) {
        String text = "";
        for (Map<String, String> m : ctx.messages()) {
            if ("user".equals(m.get("role"))) {
                text = String.valueOf(m.get("content"));
            }
        }
        return text;
    }

    private String historyText(ChatRequest request) {
        if (request.getHistory() == null || request.getHistory().isEmpty()) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        for (ChatRequest.HistoryMsg h : request.getHistory()) {
            if (StringUtils.hasText(h.getContent())) {
                sb.append(h.getContent()).append('\n');
            }
        }
        return sb.toString();
    }

    /** 缓存命中时直接组装响应：token 计 0，成本为 0，保留路由/护栏元信息 */
    private ChatResponseVO cacheHitResponse(CacheService.Hit hit, String model, ModelRouter.Decision route,
                                            GuardService.Decision in, RagService.RagContext ctx, long t0) {
        ChatResponseVO vo = new ChatResponseVO();
        vo.setAnswer(hit.answer());
        vo.setModel(model);
        vo.setRefs(hit.refs());
        vo.setFallback(false);
        vo.setDegraded(false);
        vo.setRetrievalMs(ctx.retrievalMs());
        vo.setLatencyMs(System.currentTimeMillis() - t0);
        vo.setUsage(new ChatResponseVO.Usage(0, 0, 0));
        vo.setCache(cacheMeta(hit));
        if (guard.enabled()) {
            vo.setGuard(guardMeta(in, null));
        }
        if (route != null) {
            vo.setRoute(routeMeta(route));
        }
        return vo;
    }

    /** 检索降级时不参与缓存，避免把“无知识”答案写进缓存被后续命中 */
    private CacheService.Probe probeCache(Long tenantId, String question, String scope, String model,
                                          RagService.RagContext ctx) {
        if (!cache.enabled() || ctx.fallback() || ctx.unavailable() || ctx.noKbBasis()) {
            return new CacheService.Probe("", null, null);
        }
        return cache.probe(tenantId, question, scope, model);
    }

    private Map<String, Object> cacheMeta(CacheService.Hit hit) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("hit", true);
        m.put("similarity", hit.similarity());
        m.put("exact", hit.exact());
        m.put("matchedQuestion", hit.matchedQuestion());
        m.put("ageSeconds", hit.ageSeconds());
        m.put("threshold", cache.threshold());
        return m;
    }

    private Map<String, Object> cacheMissMeta() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("hit", false);
        m.put("threshold", cache.threshold());
        return m;
    }

    /**
     * 检索上下文指纹：租户内同工单、同历史、同知识引用才视为同一缓存桶。
     * 问题本身不参与指纹（否则同义改写必然指纹不同，无法语义命中）。
     */
    private String cacheScope(ChatRequest request, RagService.RagContext ctx) {
        StringBuilder sb = new StringBuilder();
        sb.append("ticket=").append(request.getTicketId())
                .append(";history=").append(historyText(request)).append(';');
        if (ctx.refs() != null) {
            for (KbRef r : ctx.refs()) {
                sb.append(r.id()).append(':').append(r.title()).append('|');
            }
        }
        return sha256(sb.toString());
    }

    private static String sha256(String s) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] d = md.digest(s.getBytes(StandardCharsets.UTF_8));
            StringBuilder hex = new StringBuilder(d.length * 2);
            for (byte b : d) {
                hex.append(String.format("%02x", b));
            }
            return hex.toString();
        } catch (Exception e) {
            return Integer.toHexString(s.hashCode());
        }
    }

    private Map<String, Object> guardMeta(GuardService.Decision in, GuardService.Filtered out) {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("inputScore", in.score());
        m.put("inputReasons", in.reasons());
        m.put("outputBlocked", out != null && out.blocked());
        m.put("outputReasons", out == null ? List.of() : out.reasons());
        return m;
    }

    private AiCallLog baseLog(Long tenantId, String scene, RagService.RagContext ctx, long latencyMs,
                              String model) {
        AiCallLog row = new AiCallLog();
        row.setTenantId(tenantId);
        row.setScene(scene);
        row.setModel(model);
        row.setLatencyMs(latencyMs);
        row.setRefCount(ctx.refs() == null ? 0 : ctx.refs().size());
        row.setDegraded(ctx.fallback());
        row.setGuardBlocked(false);
        row.setPromptVersion(ctx.promptVersion());
        row.setTraceId(AiTrace.id());
        return row;
    }

    private void useageRecord(AiCallLog row) {
        usageService.record(row);
    }

    private List<Message> toMessages(List<Map<String, String>> raw) {
        List<Message> messages = new ArrayList<>(raw.size());
        for (Map<String, String> m : raw) {
            String role = m.get("role");
            String content = m.get("content");
            if (!StringUtils.hasText(content)) {
                continue;
            }
            switch (role == null ? "user" : role) {
                case "system" -> messages.add(new SystemMessage(content));
                case "assistant" -> messages.add(new AssistantMessage(content));
                default -> messages.add(new UserMessage(content));
            }
        }
        return messages;
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }
}
