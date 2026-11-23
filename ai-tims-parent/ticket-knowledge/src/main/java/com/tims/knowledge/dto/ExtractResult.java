package com.tims.knowledge.dto;

import java.util.List;
import java.util.Map;

/** ticket-ai 内部抽取接口返回的结构化知识（M6）。 */
public class ExtractResult {

    private String title;

    private String deviceType;

    private String faultPhenomenon;

    private String troubleshootSteps;

    private String solutionSteps;

    private List<String> tags;

    private String keyPoints;

    /** 链式模式五元组字段（单轮模式为 null，按空值降级） */
    private String rootCause;

    private String rootCauseEvidence;

    private String verification;

    private String verificationEvidence;

    private List<Map<String, String>> excludedHypotheses;

    private List<Map<String, String>> applyConditions;

    private String conditionKeys;

    private Boolean hasFinalRootCause;

    private String chainTrace;

    private Boolean chainDegraded;

    private List<String> chainErrors;

    private String model;

    private Integer promptTokens;

    private Integer completionTokens;

    private Integer totalTokens;

    private Long latencyMs;

    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getDeviceType() { return deviceType; }
    public void setDeviceType(String deviceType) { this.deviceType = deviceType; }
    public String getFaultPhenomenon() { return faultPhenomenon; }
    public void setFaultPhenomenon(String faultPhenomenon) { this.faultPhenomenon = faultPhenomenon; }
    public String getTroubleshootSteps() { return troubleshootSteps; }
    public void setTroubleshootSteps(String troubleshootSteps) { this.troubleshootSteps = troubleshootSteps; }
    public String getSolutionSteps() { return solutionSteps; }
    public void setSolutionSteps(String solutionSteps) { this.solutionSteps = solutionSteps; }
    public List<String> getTags() { return tags; }
    public void setTags(List<String> tags) { this.tags = tags; }
    public String getKeyPoints() { return keyPoints; }
    public void setKeyPoints(String keyPoints) { this.keyPoints = keyPoints; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public Integer getPromptTokens() { return promptTokens; }
    public void setPromptTokens(Integer promptTokens) { this.promptTokens = promptTokens; }
    public Integer getCompletionTokens() { return completionTokens; }
    public void setCompletionTokens(Integer completionTokens) { this.completionTokens = completionTokens; }
    public Integer getTotalTokens() { return totalTokens; }
    public void setTotalTokens(Integer totalTokens) { this.totalTokens = totalTokens; }
    public Long getLatencyMs() { return latencyMs; }
    public void setLatencyMs(Long latencyMs) { this.latencyMs = latencyMs; }
    public String getRootCause() { return rootCause; }
    public void setRootCause(String rootCause) { this.rootCause = rootCause; }
    public String getRootCauseEvidence() { return rootCauseEvidence; }
    public void setRootCauseEvidence(String rootCauseEvidence) { this.rootCauseEvidence = rootCauseEvidence; }
    public String getVerification() { return verification; }
    public void setVerification(String verification) { this.verification = verification; }
    public String getVerificationEvidence() { return verificationEvidence; }
    public void setVerificationEvidence(String verificationEvidence) { this.verificationEvidence = verificationEvidence; }
    public List<Map<String, String>> getExcludedHypotheses() { return excludedHypotheses; }
    public void setExcludedHypotheses(List<Map<String, String>> excludedHypotheses) { this.excludedHypotheses = excludedHypotheses; }
    public List<Map<String, String>> getApplyConditions() { return applyConditions; }
    public void setApplyConditions(List<Map<String, String>> applyConditions) { this.applyConditions = applyConditions; }
    public String getConditionKeys() { return conditionKeys; }
    public void setConditionKeys(String conditionKeys) { this.conditionKeys = conditionKeys; }
    public Boolean getHasFinalRootCause() { return hasFinalRootCause; }
    public void setHasFinalRootCause(Boolean hasFinalRootCause) { this.hasFinalRootCause = hasFinalRootCause; }
    public String getChainTrace() { return chainTrace; }
    public void setChainTrace(String chainTrace) { this.chainTrace = chainTrace; }
    public Boolean getChainDegraded() { return chainDegraded; }
    public void setChainDegraded(Boolean chainDegraded) { this.chainDegraded = chainDegraded; }
    public List<String> getChainErrors() { return chainErrors; }
    public void setChainErrors(List<String> chainErrors) { this.chainErrors = chainErrors; }
}
