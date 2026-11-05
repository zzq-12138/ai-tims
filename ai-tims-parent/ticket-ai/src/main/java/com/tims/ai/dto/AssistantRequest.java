package com.tims.ai.dto;

import java.util.List;

/** 工单助手请求：单轮 message + 可选多轮历史 + 会话归属 */
public class AssistantRequest {

    private String message;
    /** 会话 id：传了就按后端会话窗口取历史；不传则自动建会话 */
    private Long sessionId;
    /** 兼容旧调用：无 sessionId 时的前端历史 */
    private List<ChatRequest.HistoryMsg> history;

    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }
    public Long getSessionId() { return sessionId; }
    public void setSessionId(Long sessionId) { this.sessionId = sessionId; }
    public List<ChatRequest.HistoryMsg> getHistory() { return history; }
    public void setHistory(List<ChatRequest.HistoryMsg> history) { this.history = history; }
}
