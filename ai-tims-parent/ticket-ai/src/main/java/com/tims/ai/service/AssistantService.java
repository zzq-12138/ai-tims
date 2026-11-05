package com.tims.ai.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.ai.chat.AiChatMessage;
import com.tims.ai.chat.AiChatSession;
import com.tims.ai.chat.AiChatSessionService;
import com.tims.ai.config.AiProperties;
import com.tims.ai.dto.AssistantRequest;
import com.tims.ai.dto.AssistantVO;
import com.tims.ai.dto.ChatRequest;
import com.tims.ai.dto.ChatResponseVO;
import com.tims.ai.llm.LlmException;
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

    private static final String SYSTEM_PROMPT = """
            你是 AI-TIMS 智能制造工单系统的工单助手，服务设备工程师与产线主管。
            你可以调用工具：
            - query_ticket_status：查工单状态/进度
            - search_knowledge：检索维修知识库
            - ticket_statistics：查工单统计概览
            规则：
            1. 用户问工单进度、故障处理办法、工单统计时，必须先调用对应工具，不要凭记忆编造。
            2. 用户消息中出现工单编号（WO 开头）或工单 ID 时，直接调用 query_ticket_status(keyword=该编号/ID)，不要反问。
            3. 工具结果不足或为空时如实说明，不虚构工单号、参数或统计数字。
            4. 回答简洁、可执行，中文 Markdown；引用知识用 [K1] 形式标注。
            """;

    private final ChatClient chatClient;
    private final TicketTools ticketTools;
    private final AiProperties props;
    private final AiUsageService usageService;
    private final AiChatSessionService sessionService;
    private final ObjectMapper mapper;

    public AssistantService(ChatClient chatClient, TicketTools ticketTools,
                            AiProperties props, AiUsageService usageService,
                            AiChatSessionService sessionService, ObjectMapper mapper) {
        this.chatClient = chatClient;
        this.ticketTools = ticketTools;
        this.props = props;
        this.usageService = usageService;
        this.sessionService = sessionService;
        this.mapper = mapper;
    }

    public AssistantVO chat(Long tenantId, AssistantRequest request) {
        if (!StringUtils.hasText(request.getMessage())) {
            throw new BizException(10400, "message 必填");
        }
        Long tid = tenantId == null ? 1L : tenantId;
        Long uid = request.getUserId();
        if (uid == null) {
            throw new BizException(10400, "userId 必填");
        }

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
        // 先落用户消息：即使模型超时，刷新后也能看到该问题
        sessionService.addMessage(tid, uid, session.getId(), "user", request.getMessage(), null, null, null);
        sessionService.touch(session, request.getMessage());

        long t0 = System.currentTimeMillis();
        ToolCallRecorder.begin();
        try {
            List<Message> promptMessages = new ArrayList<>(history);
            promptMessages.add(new UserMessage(request.getMessage()));
            ChatResponse resp = chatClient.prompt()
                    .system(SYSTEM_PROMPT)
                    .messages(promptMessages)
                    .tools(ticketTools)
                    .call()
                    .chatResponse();

            String answer = resp.getResult() == null ? "" : resp.getResult().getOutput().getText();
            List<ToolCallRecorder.Record> records = ToolCallRecorder.snapshot();
            Usage u = resp.getMetadata() == null ? null : resp.getMetadata().getUsage();
            int prompt = u == null || u.getPromptTokens() == null ? 0 : u.getPromptTokens();
            int completion = u == null || u.getCompletionTokens() == null ? 0 : u.getCompletionTokens();
            long total = System.currentTimeMillis() - t0;
            boolean degraded = records.stream().anyMatch(ToolCallRecorder.Record::degraded);

            AssistantVO vo = new AssistantVO();
            vo.setAnswer(answer);
            vo.setModel(props.getModel());
            vo.setLatencyMs(total);
            vo.setDegraded(degraded);
            vo.setUsage(new ChatResponseVO.Usage(prompt, completion, prompt + completion));
            vo.setToolCalls(records);
            vo.setSessionId(session.getId());
            vo.setSessionTitle(session.getTitle());

            sessionService.addMessage(tid, uid, session.getId(), "assistant", answer,
                    props.getModel(), toJson(records), toJson(vo.getUsage()));
            sessionService.touchOnly(session.getId());

            persistAgent(tid, total, prompt, completion, degraded, records, null);
            log.info("[assistant] done session={} model={} tools={} usage={}/{} total={}ms",
                    session.getId(), props.getModel(), records.size(), prompt, completion, total);
            return vo;
        } catch (Exception e) {
            long total = System.currentTimeMillis() - t0;
            String err = truncate(e.getMessage(), 250);
            sessionService.addMessage(tid, uid, session.getId(), "assistant",
                    "调用失败：" + (e.getMessage() == null ? "AI 服务不可用" : e.getMessage()), props.getModel(), null, null);
            sessionService.touchOnly(session.getId());
            persistAgent(tid, total, 0, 0, true, ToolCallRecorder.snapshot(), e.getMessage());
            log.error("[assistant] failed session={}: {}", session.getId(), e.getMessage());
            if (e instanceof LlmException le) {
                throw le;
            }
            throw new LlmException(40201, "AI 助手暂不可用：" + e.getMessage());
        } finally {
            ToolCallRecorder.clear();
        }
    }

    private void persistAgent(Long tenantId, long total, int prompt, int completion, boolean degraded,
                              List<ToolCallRecorder.Record> records, String error) {
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
        row.setErrorMsg(error == null ? null : truncate(error, 250));
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
            t.setErrorMsg("OK".equals(r.status()) ? null : truncate(r.summary(), 250));
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
                messages.add(new AssistantMessage(m.getContent()));
            } else if ("user".equals(m.getRole())) {
                messages.add(new UserMessage(m.getContent()));
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
                messages.add(new AssistantMessage(m.getContent()));
            } else if ("user".equals(m.getRole())) {
                messages.add(new UserMessage(m.getContent()));
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
