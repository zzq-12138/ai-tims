package com.tims.ai.dto;

import com.fasterxml.jackson.annotation.JsonInclude;
import com.fasterxml.jackson.databind.annotation.JsonSerialize;
import com.fasterxml.jackson.databind.ser.std.ToStringSerializer;

import java.util.List;
import java.util.Map;

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

    /** 护栏开启时返回的命中选择信息（关闭时不返回，保持原契约） */
    private Map<String, Object> guard;

    /** 路由开启时返回选中的模型与命中信号（关闭时不返回，保持原契约） */
    private Map<String, Object> route;

    /** 语义缓存开启时返回命中信息（关闭时不返回，保持原契约） */
    private Map<String, Object> cache;

    /** C 档兜底开关开启且命中 C 档时返回；关闭时不序列化，保持原契约 */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    private String tier;

    @JsonInclude(JsonInclude.Include.NON_NULL)
    private String tierReason;

    @JsonInclude(JsonInclude.Include.NON_NULL)
    private Boolean noKbBasis;

    /** 兜底建议落库 id，用于工单关闭后回填实际处置（雪花 ID 按字符串下发，避免前端 Number 精度丢失） */
    @JsonInclude(JsonInclude.Include.NON_NULL)
    @JsonSerialize(using = ToStringSerializer.class)
    private Long suggestionId;

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
    public Map<String, Object> getGuard() { return guard; }
    public void setGuard(Map<String, Object> guard) { this.guard = guard; }
    public Map<String, Object> getRoute() { return route; }
    public void setRoute(Map<String, Object> route) { this.route = route; }
    public Map<String, Object> getCache() { return cache; }
    public void setCache(Map<String, Object> cache) { this.cache = cache; }
    public String getTier() { return tier; }
    public void setTier(String tier) { this.tier = tier; }
    public String getTierReason() { return tierReason; }
    public void setTierReason(String tierReason) { this.tierReason = tierReason; }
    public Boolean getNoKbBasis() { return noKbBasis; }
    public void setNoKbBasis(Boolean noKbBasis) { this.noKbBasis = noKbBasis; }
    public Long getSuggestionId() { return suggestionId; }
    public void setSuggestionId(Long suggestionId) { this.suggestionId = suggestionId; }

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
