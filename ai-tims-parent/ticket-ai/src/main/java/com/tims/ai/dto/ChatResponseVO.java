package com.tims.ai.dto;

import java.util.List;

/** 同步问答响应 */
public class ChatResponseVO {

    private String answer;
    private String model;
    private List<?> refs;
    private boolean fallback;
    private boolean degraded;
    private String degradedNote;
    private long retrievalMs;
    private long latencyMs;
    private Usage usage;

    public String getAnswer() { return answer; }
    public void setAnswer(String answer) { this.answer = answer; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public List<?> getRefs() { return refs; }
    public void setRefs(List<?> refs) { this.refs = refs; }
    public boolean isFallback() { return fallback; }
    public void setFallback(boolean fallback) { this.fallback = fallback; }
    public boolean isDegraded() { return degraded; }
    public void setDegraded(boolean degraded) { this.degraded = degraded; }
    public String getDegradedNote() { return degradedNote; }
    public void setDegradedNote(String degradedNote) { this.degradedNote = degradedNote; }
    public long getRetrievalMs() { return retrievalMs; }
    public void setRetrievalMs(long retrievalMs) { this.retrievalMs = retrievalMs; }
    public long getLatencyMs() { return latencyMs; }
    public void setLatencyMs(long latencyMs) { this.latencyMs = latencyMs; }
    public Usage getUsage() { return usage; }
    public void setUsage(Usage usage) { this.usage = usage; }

    /** token 用量 */
    public static class Usage {
        private int promptTokens;
        private int completionTokens;
        private int totalTokens;

        public Usage() { }
        public Usage(int promptTokens, int completionTokens, int totalTokens) {
            this.promptTokens = promptTokens;
            this.completionTokens = completionTokens;
            this.totalTokens = totalTokens;
        }
        public int getPromptTokens() { return promptTokens; }
        public void setPromptTokens(int promptTokens) { this.promptTokens = promptTokens; }
        public int getCompletionTokens() { return completionTokens; }
        public void setCompletionTokens(int completionTokens) { this.completionTokens = completionTokens; }
        public int getTotalTokens() { return totalTokens; }
        public void setTotalTokens(int totalTokens) { this.totalTokens = totalTokens; }
    }
}
