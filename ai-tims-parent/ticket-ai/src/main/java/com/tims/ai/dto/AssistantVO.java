package com.tims.ai.dto;

import com.tims.ai.tool.ToolCallRecorder;

import java.util.List;
import java.util.Map;

/** 工单助手响应：答案 + token 用量 + 本次触发的工具调用明细 + 会话信息 */
public class AssistantVO {

    private String answer;
    private String model;
    private long latencyMs;
    private boolean degraded;
    private ChatResponseVO.Usage usage;
    private List<ToolCallRecorder.Record> toolCalls;
    private Long sessionId;
    private String sessionTitle;
    /** 本次落库的用户消息/助手消息 ID，前端用于立即支持复制引用与撤回 */
    private Long userMessageId;
    private Long assistantMessageId;

    /** 护栏开启时返回的命中选择信息（关闭时不返回） */
    private Map<String, Object> guard;

    public String getAnswer() { return answer; }
    public void setAnswer(String answer) { this.answer = answer; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public long getLatencyMs() { return latencyMs; }
    public void setLatencyMs(long latencyMs) { this.latencyMs = latencyMs; }
    public boolean isDegraded() { return degraded; }
    public void setDegraded(boolean degraded) { this.degraded = degraded; }
    public ChatResponseVO.Usage getUsage() { return usage; }
    public void setUsage(ChatResponseVO.Usage usage) { this.usage = usage; }
    public List<ToolCallRecorder.Record> getToolCalls() { return toolCalls; }
    public void setToolCalls(List<ToolCallRecorder.Record> toolCalls) { this.toolCalls = toolCalls; }
    public Long getSessionId() { return sessionId; }
    public void setSessionId(Long sessionId) { this.sessionId = sessionId; }
    public String getSessionTitle() { return sessionTitle; }
    public void setSessionTitle(String sessionTitle) { this.sessionTitle = sessionTitle; }
    public Long getUserMessageId() { return userMessageId; }
    public void setUserMessageId(Long userMessageId) { this.userMessageId = userMessageId; }
    public Long getAssistantMessageId() { return assistantMessageId; }
    public void setAssistantMessageId(Long assistantMessageId) { this.assistantMessageId = assistantMessageId; }
    public Map<String, Object> getGuard() { return guard; }
    public void setGuard(Map<String, Object> guard) { this.guard = guard; }
}
