package com.tims.ai.dto;

import java.util.List;

/** 工单助手请求：单轮 message + 可选多轮历史 */
public class AssistantRequest {

    private String message;
    private List<ChatRequest.HistoryMsg> history;

    public String getMessage() { return message; }
    public void setMessage(String message) { this.message = message; }
    public List<ChatRequest.HistoryMsg> getHistory() { return history; }
    public void setHistory(List<ChatRequest.HistoryMsg> history) { this.history = history; }
}
