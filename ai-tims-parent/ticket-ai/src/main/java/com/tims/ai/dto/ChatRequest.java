package com.tims.ai.dto;

import java.util.List;

/** AI 对话请求（RAG 流式/同步共用） */
public class ChatRequest {

    /** 用户问题 */
    private String question;

    /** 可选：关联工单 ID，用于注入工单上下文与知识检索加权 */
    private Long ticketId;

    /** 可选：多轮历史（最多保留最近 6 条） */
    private List<HistoryMsg> history;

    /** 可选：检索 TopK，默认 5 */
    private Integer topK;

    public String getQuestion() { return question; }
    public void setQuestion(String question) { this.question = question; }
    public Long getTicketId() { return ticketId; }
    public void setTicketId(Long ticketId) { this.ticketId = ticketId; }
    public List<HistoryMsg> getHistory() { return history; }
    public void setHistory(List<HistoryMsg> history) { this.history = history; }
    public Integer getTopK() { return topK; }
    public void setTopK(Integer topK) { this.topK = topK; }

    /** 一条历史消息 */
    public static class HistoryMsg {
        private String role;
        private String content;

        public String getRole() { return role; }
        public void setRole(String role) { this.role = role; }
        public String getContent() { return content; }
        public void setContent(String content) { this.content = content; }
    }
}
