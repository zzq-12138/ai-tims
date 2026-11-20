package com.tims.ai.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.ai.apikey.AiTenantContext;
import com.tims.ai.chat.AiChatMessage;
import com.tims.ai.chat.AiChatSession;
import com.tims.ai.chat.AiChatSessionService;
import com.tims.ai.config.AiProperties;
import com.tims.ai.dto.AssistantRequest;
import com.tims.ai.dto.AssistantVO;
import com.tims.ai.dto.ChatRequest;
import com.tims.ai.dto.ChatResponseVO;
import com.tims.ai.guard.GuardService;
import com.tims.ai.llm.LlmException;
import com.tims.ai.observe.AiTrace;
import com.tims.ai.prompt.PromptRegistry;
import com.tims.ai.tool.TicketTools;
import com.tims.ai.tool.ToolCallRecorder;
import com.tims.ai.usage.AiCallLog;
import com.tims.ai.usage.AiUsageService;
import com.tims.common.exception.BizException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;

/**
 * 工单助手：ChatClient + 3 个 @Tool（Spring AI 内部完成工具调用循环）。
 * 工具调用明细回传前端并落 ai_call_log(scene=AGENT_TOOL)，可查“调了哪个工具/参数/耗时”。
 *
 * 多轮上下文（M6 问题8）：以 sessionId 为准，历史取自 ai_chat_message 的最近 10 条，
 * 前端不再需要回传整段历史；刷新/切会话/换设备后上下文一致。
 */
@Service
public class AssistantService {

    private static final Logger log = LoggerFactory.getLogger(AssistantService.class);

    private final ChatClient chatClient;
    private final TicketTools ticketTools;
    private final AiProperties props;
    private final AiUsageService usageService;
    private final AiChatSessionService sessionService;
    private final ObjectMapper mapper;
    private final GuardService guard;
    private final PromptRegistry promptRegistry;

    public AssistantService(ChatClient chatClient, TicketTools ticketTools,
                            AiProperties props, AiUsageService usageService,
                            AiChatSessionService sessionService, ObjectMapper mapper,
                            GuardService guard, PromptRegistry promptRegistry) {
        this.chatClient = chatClient;
        this.ticketTools = ticketTools;
        this.props = props;
        this.usageService = usageService;
        this.sessionService = sessionService;
        this.mapper = mapper;
        this.guard = guard;
        this.promptRegistry = promptRegistry;
    }

    public AssistantVO chat(Long tenantId, Long userId, AssistantRequest request) {
        if (!StringUtils.hasText(request.getMessage())) {
            throw new BizException(10400, "message 必填");
        }
        Long tid = tenantId == null ? 1L : tenantId;
        if (userId == null) {
            throw new BizException(10401, "未登录或凭证失效");
        }
        Long uid = userId;

        GuardService.Decision in = guard.inspectInput(request.getMessage());
        if (in.blocked()) {
            recordBlocked(tid, uid, "请求被安全护栏拦截：" + String.join(",", in.reasons()));
            throw new LlmException(40301, "请求被安全护栏拦截：" + String.join(",", in.reasons()));
        }
        String userMessage = guard.mask(request.getMessage());
        AiTrace.start();

        // 会话：传 sessionId 则校验归属并读库内窗口；否则自动建会话
        AiChatSession session;
        List<Message> history;
        if (request.getSessionId() != null) {
            session = sessionService.require(tid, uid, request.getSessionId());
            history = toMessagesFromDb(sessionService.recentWindow(tid, uid, session.getId()));
        } else {
            session = sessionService.create(tid, uid, null);
            history = toMessagesFromHistory(request.getHistory());
        }
        // 引用回复：校验被引用消息属于同一会话，并保存快照（截断），刷新后引用关系仍在
        AiChatMessage quoted = null;
        if (request.getQuotedMessageId() != null) {
            quoted = sessionService.requireMessage(tid, uid, session.getId(), request.getQuotedMessageId());
        }
        String quotedContent = quoted == null ? null : truncate(quoted.getContent(), 200);
        // 先落用户消息：即使模型超时，刷新后也能看到该问题
        AiChatMessage userRow = sessionService.addMessage(tid, uid, session.getId(), "user", userMessage,
                null, null, null, quoted == null ? null : quoted.getId(),
                quoted == null ? null : quoted.getRole(), quotedContent);
        sessionService.touch(session, userMessage);

        PromptRegistry.Active sysPrompt = promptRegistry.active(tid, "ASSISTANT");
        long t0 = System.currentTimeMillis();
        ToolCallRecorder.begin();
        try {
            List<Message> promptMessages = new ArrayList<>(history);
            promptMessages.add(new UserMessage(userMessage));
            ChatResponse resp;
            AiTenantContext.set(tid);
            try {
                resp = chatClient.prompt()
                        .system(sysPrompt.content())
                        .messages(promptMessages)
                        .tools(ticketTools)
                        .call()
                        .chatResponse();
            } finally {
                AiTenantContext.clear();
            }

            GuardService.Filtered filtered = guard.filterOutput(
                    resp.getResult() == null ? "" : resp.getResult().getOutput().getText());
            String answer = filtered.text();
            List<ToolCallRecorder.Record> records = ToolCallRecorder.snapshot();
            Usage u = resp.getMetadata() == null ? null : resp.getMetadata().getUsage();
            int prompt = u == null || u.getPromptTokens() == null ? 0 : u.getPromptTokens();
            int completion = u == null || u.getCompletionTokens() == null ? 0 : u.getCompletionTokens();
            long total = System.currentTimeMillis() - t0;
            boolean degraded = filtered.blocked()
                    || records.stream().anyMatch(ToolCallRecorder.Record::degraded);

            AssistantVO vo = new AssistantVO();
            vo.setAnswer(answer);
            vo.setModel(props.getModel());
            vo.setLatencyMs(total);
            vo.setDegraded(degraded);
            vo.setUsage(new ChatResponseVO.Usage(prompt, completion, prompt + completion));
            vo.setToolCalls(records);
            vo.setSessionId(session.getId());
            vo.setSessionTitle(session.getTitle());
            vo.setUserMessageId(userRow.getId());
            if (guard.enabled()) {
                java.util.Map<String, Object> gm = new java.util.LinkedHashMap<>();
                gm.put("inputScore", in.score());
                gm.put("inputReasons", in.reasons());
                gm.put("outputBlocked", filtered.blocked());
                gm.put("outputReasons", filtered.reasons());
                vo.setGuard(gm);
            }

            AiChatMessage aiRow = sessionService.addMessage(tid, uid, session.getId(), "assistant", answer,
                    props.getModel(), toJson(records), toJson(vo.getUsage()));
            vo.setAssistantMessageId(aiRow.getId());
            sessionService.touchOnly(session.getId());

            persistAgent(tid, uid, sysPrompt.version(), filtered.blocked(), total, prompt, completion,
                    degraded, records, null);
            log.info("[assistant] done session={} model={} tools={} usage={}/{} total={}ms",
                    session.getId(), props.getModel(), records.size(), prompt, completion, total);
            return vo;
        } catch (Exception e) {
            long total = System.currentTimeMillis() - t0;
            String err = truncate(e.getMessage(), 250);
            sessionService.addMessage(tid, uid, session.getId(), "assistant",
                    "调用失败：" + (e.getMessage() == null ? "AI 服务不可用" : e.getMessage()), props.getModel(), null, null);
            sessionService.touchOnly(session.getId());
            persistAgent(tid, uid, sysPrompt.version(), false, total, 0, 0, true,
                    ToolCallRecorder.snapshot(), e.getMessage());
            log.error("[assistant] failed session={}: {}", session.getId(), e.getMessage());
            if (e instanceof LlmException le) {
                throw le;
            }
            throw new LlmException(40201, "AI 助手暂不可用：" + e.getMessage());
        } finally {
            ToolCallRecorder.clear();
            AiTrace.clear();
        }
    }

    /** 护栏拦截也要留痕：护栏本身不放行，但观测面板能看到被拦的请求 */
    private void recordBlocked(Long tenantId, Long userId, String reason) {
        AiTrace.start();
        try {
            AiCallLog row = new AiCallLog();
            row.setTenantId(tenantId);
            row.setScene("AGENT");
            row.setModel(props.getModel());
            row.setPromptTokens(0);
            row.setCompletionTokens(0);
            row.setTotalTokens(0);
            row.setLatencyMs(0L);
            row.setStatus("BLOCKED");
            row.setDegraded(false);
            row.setGuardBlocked(true);
            row.setPromptVersion("guard-v1");
            row.setTraceId(AiTrace.id());
            row.setUserId(userId);
            row.setErrorMsg(truncate(reason, 250));
            usageService.record(row);
        } finally {
            AiTrace.clear();
        }
    }

    private void persistAgent(Long tenantId, Long userId, String promptVersion, boolean guardBlocked,
                              long total, int prompt, int completion, boolean degraded,
                              List<ToolCallRecorder.Record> records, String error) {
        String traceId = AiTrace.id();
        AiCallLog row = new AiCallLog();
        row.setTenantId(tenantId);
        row.setScene("AGENT");
        row.setModel(props.getModel());
        row.setPromptTokens(prompt);
        row.setCompletionTokens(completion);
        row.setTotalTokens(prompt + completion);
        row.setLatencyMs(total);
        row.setStatus(error == null ? (degraded ? "DEGRADED" : "SUCCESS") : "ERROR");
        row.setDegraded(degraded);
        row.setGuardBlocked(guardBlocked);
        row.setPromptVersion(promptVersion);
        row.setTraceId(traceId);
        row.setUserId(userId);
        row.setErrorMsg(error == null ? null : truncate(error, 250));
        // 本次问答的引用数：所有 search_knowledge 命中按知识 id 去重后计数，避免多次检索重复累加
        java.util.Set<Long> refIds = new java.util.LinkedHashSet<>();
        for (ToolCallRecorder.Record r : records) {
            refIds.addAll(r.refIds());
        }
        row.setRefCount(refIds.size());
        usageService.record(row);

        for (ToolCallRecorder.Record r : records) {
            AiCallLog t = new AiCallLog();
            t.setTenantId(tenantId);
            t.setScene("AGENT_TOOL");
            t.setModel(props.getModel());
            t.setToolName(r.name());
            t.setToolArgs(truncate(r.args(), 500));
            t.setLatencyMs(r.elapsedMs());
            t.setFirstTokenMs(r.elapsedMs());
            t.setStatus("OK".equals(r.status()) ? "SUCCESS" : "ERROR");
            t.setDegraded(r.degraded());
            t.setGuardBlocked(false);
            t.setPromptVersion(promptVersion);
            t.setTraceId(traceId);
            t.setUserId(userId);
            t.setErrorMsg("OK".equals(r.status()) ? null : truncate(r.summary(), 250));
            // 工具行只记本次 search_knowledge 实际命中条数；其他工具为 0
            t.setRefCount(r.refCount());
            usageService.record(t);
        }
    }

    private List<Message> toMessagesFromDb(List<AiChatMessage> rows) {
        List<Message> messages = new ArrayList<>();
        for (AiChatMessage m : rows) {
            if (!StringUtils.hasText(m.getContent())) {
                continue;
            }
            if ("assistant".equals(m.getRole())) {
                messages.add(new AssistantMessage(guard.mask(m.getContent())));
            } else if ("user".equals(m.getRole())) {
                messages.add(new UserMessage(guard.mask(m.getContent())));
            }
        }
        return messages;
    }

    private List<Message> toMessagesFromHistory(List<ChatRequest.HistoryMsg> history) {
        List<Message> messages = new ArrayList<>();
        if (history == null) {
            return messages;
        }
        int from = Math.max(0, history.size() - 6);
        for (ChatRequest.HistoryMsg m : history.subList(from, history.size())) {
            if (!StringUtils.hasText(m.getContent())) {
                continue;
            }
            if ("assistant".equals(m.getRole())) {
                messages.add(new AssistantMessage(guard.mask(m.getContent())));
            } else if ("user".equals(m.getRole())) {
                messages.add(new UserMessage(guard.mask(m.getContent())));
            }
        }
        return messages;
    }

    private String toJson(Object v) {
        try {
            return v == null ? null : mapper.writeValueAsString(v);
        } catch (Exception e) {
            return null;
        }
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }
}
