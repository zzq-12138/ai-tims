package com.tims.knowledge.dto;

import java.math.BigDecimal;

/** 建议→回填：ticket-ai 回填处置后投递的待审条目（只入 ai_extracted，不直写知识库）。 */
public class FallbackIntakeRequest {

    private Long tenantId;

    /** ai_fallback_pair.id */
    private Long fallbackPairId;

    private Long ticketId;

    private String ticketNo;

    /** 问答会话ID（可空） */
    private String sessionId;

    private String model;

    private String promptVersion;

    /** 置信分 0-1（coverage 优先，其次 dice） */
    private BigDecimal confidence;

    private String coverageVerdict;

    private String suggestionText;

    /** 人工回填的实际处置（作为待审条目的正文来源） */
    private String actualDisposition;

    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public Long getFallbackPairId() { return fallbackPairId; }
    public void setFallbackPairId(Long fallbackPairId) { this.fallbackPairId = fallbackPairId; }
    public Long getTicketId() { return ticketId; }
    public void setTicketId(Long ticketId) { this.ticketId = ticketId; }
    public String getTicketNo() { return ticketNo; }
    public void setTicketNo(String ticketNo) { this.ticketNo = ticketNo; }
    public String getSessionId() { return sessionId; }
    public void setSessionId(String sessionId) { this.sessionId = sessionId; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public String getPromptVersion() { return promptVersion; }
    public void setPromptVersion(String promptVersion) { this.promptVersion = promptVersion; }
    public BigDecimal getConfidence() { return confidence; }
    public void setConfidence(BigDecimal confidence) { this.confidence = confidence; }
    public String getCoverageVerdict() { return coverageVerdict; }
    public void setCoverageVerdict(String coverageVerdict) { this.coverageVerdict = coverageVerdict; }
    public String getSuggestionText() { return suggestionText; }
    public void setSuggestionText(String suggestionText) { this.suggestionText = suggestionText; }
    public String getActualDisposition() { return actualDisposition; }
    public void setActualDisposition(String actualDisposition) { this.actualDisposition = actualDisposition; }
}
