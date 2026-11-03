package com.tims.ai.service;

import com.tims.ai.config.AiProperties;
import com.tims.ai.dto.ChatRequest;
import com.tims.ai.dto.ChatResponseVO;
import com.tims.ai.llm.LlmException;
import com.tims.ai.llm.ZhipuStreamClient;
import com.tims.ai.rag.RagService;
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
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

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

    public ChatService(RagService ragService, ZhipuStreamClient streamClient,
                       OpenAiChatModel chatModel, AiProperties props, AiUsageService usageService) {
        this.ragService = ragService;
        this.streamClient = streamClient;
        this.chatModel = chatModel;
        this.props = props;
        this.usageService = usageService;
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
        RagService.RagContext ctx = ragService.prepare(tenantId, request);
        try {
            ChatResponse resp = chatModel.call(new Prompt(toMessages(ctx.messages())));
            String answer = resp.getResult() == null ? "" : resp.getResult().getOutput().getText();
            Usage u = resp.getMetadata() == null ? null : resp.getMetadata().getUsage();
            int prompt = u == null || u.getPromptTokens() == null ? 0 : u.getPromptTokens();
            int completion = u == null || u.getCompletionTokens() == null ? 0 : u.getCompletionTokens();
            long total = System.currentTimeMillis() - t0;

            ChatResponseVO vo = new ChatResponseVO();
            vo.setAnswer(ctx.degradedNote() == null ? answer : ctx.degradedNote() + "\n\n" + answer);
            vo.setModel(props.getModel());
            vo.setRefs(ctx.refs());
            vo.setFallback(ctx.fallback());
            vo.setDegraded(ctx.fallback());
            vo.setDegradedNote(ctx.degradedNote());
            vo.setRetrievalMs(ctx.retrievalMs());
            vo.setLatencyMs(total);
            vo.setUsage(new ChatResponseVO.Usage(prompt, completion, prompt + completion));

            AiCallLog row = baseLog(tenantId, "CHAT_SYNC", ctx, total);
            row.setPromptTokens(prompt);
            row.setCompletionTokens(completion);
            row.setTotalTokens(prompt + completion);
            row.setStatus(ctx.fallback() ? "DEGRADED" : "SUCCESS");
            useageRecord(row);
            log.info("[ai] sync done model={} prompt={} completion={} total={}ms", props.getModel(), prompt, completion, total);
            return vo;
        } catch (Exception e) {
            AiCallLog row = baseLog(tenantId, "CHAT_SYNC", ctx, System.currentTimeMillis() - t0);
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
        RagService.RagContext ctx;
        try {
            ctx = ragService.prepare(tenantId, request);
        } catch (Exception e) {
            sink.error(10400, e.getMessage());
            sink.done();
            return;
        }

        Map<String, Object> meta = new LinkedHashMap<>();
        meta.put("model", props.getModel());
        meta.put("refs", ctx.refs());
        meta.put("fallback", ctx.fallback());
        meta.put("unavailable", ctx.unavailable());
        meta.put("mode", ctx.mode());
        meta.put("retrievalMs", ctx.retrievalMs());
        meta.put("degraded", ctx.fallback() || ctx.unavailable());
        meta.put("degradedNote", ctx.degradedNote());
        sink.meta(meta);

        // 降级标注先落正文首段，保证“回答里标注”不依赖模型是否听话
        if (ctx.degradedNote() != null) {
            sink.content(ctx.degradedNote() + "\n\n");
        }

        try {
            ZhipuStreamClient.StreamResult result = streamClient.stream(
                    props.getModel(), props.getMaxTokens(), props.getTemperature(), ctx.messages(),
                    new ZhipuStreamClient.Listener() {
                        @Override
                        public void onReasoning(String delta) {
                            sink.reasoning(delta);
                        }

                        @Override
                        public void onContent(String delta) {
                            sink.content(delta);
                        }
                    });

            AiCallLog row = baseLog(tenantId, "CHAT_STREAM", ctx, result.totalMs());
            row.setPromptTokens((int) result.usage().promptTokens());
            row.setCompletionTokens((int) result.usage().completionTokens());
            row.setTotalTokens((int) result.usage().totalTokens());
            row.setReasoningTokens((int) result.usage().reasoningTokens());
            row.setFirstTokenMs(result.firstTokenMs());
            row.setStatus(ctx.fallback() ? "DEGRADED" : "SUCCESS");
            useageRecord(row);

            Map<String, Object> usage = new LinkedHashMap<>();
            usage.put("model", props.getModel());
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
            sink.usage(usage);
            sink.done();
        } catch (LlmException e) {
            AiCallLog row = baseLog(tenantId, "CHAT_STREAM", ctx, System.currentTimeMillis() - t0);
            row.setStatus("ERROR");
            row.setErrorMsg(truncate(e.getMessage(), 250));
            useageRecord(row);
            log.error("[ai] stream failed code={} msg={}", e.getCode(), e.getMessage());
            sink.error(e.getCode(), e.getMessage());
            sink.done();
        } catch (Exception e) {
            AiCallLog row = baseLog(tenantId, "CHAT_STREAM", ctx, System.currentTimeMillis() - t0);
            row.setStatus("ERROR");
            row.setErrorMsg(truncate(e.getMessage(), 250));
            useageRecord(row);
            log.error("[ai] stream failed unexpected: {}", e.getMessage());
            sink.error(40201, "AI 服务不可用：" + e.getMessage());
            sink.done();
        }
    }

    private AiCallLog baseLog(Long tenantId, String scene, RagService.RagContext ctx, long latencyMs) {
        AiCallLog row = new AiCallLog();
        row.setTenantId(tenantId);
        row.setScene(scene);
        row.setModel(props.getModel());
        row.setLatencyMs(latencyMs);
        row.setRefCount(ctx.refs() == null ? 0 : ctx.refs().size());
        row.setDegraded(ctx.fallback());
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
