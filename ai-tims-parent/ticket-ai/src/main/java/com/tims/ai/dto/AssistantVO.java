package com.tims.ai.dto;

import com.tims.ai.tool.ToolCallRecorder;

import java.util.List;

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
}
