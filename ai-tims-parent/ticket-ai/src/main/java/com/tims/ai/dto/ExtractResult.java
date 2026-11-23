package com.tims.ai.dto;

import java.util.List;
import java.util.Map;

/**
 * 结构化知识抽取结果（M6）。
 * 标题/设备类型/故障现象/排查步骤/解决步骤/标签/关键要点，统一由 GLM 输出后解析。
 * 链式模式（tims.ai.extract.chain-enabled=true）额外产出五元组字段与 chainTrace；
 * 单轮模式下这些字段为 null，行为与原有链路一致。
 */
public class ExtractResult {

    private String title;

    private String deviceType;

    private String faultPhenomenon;

    private String troubleshootSteps;

    private String solutionSteps;

    private List<String> tags;

    private String keyPoints;

    private String model;

    private Integer promptTokens;

    private Integer completionTokens;

    private Integer totalTokens;

    private Long latencyMs;

    /** 根因结论句（无最终根因时为空串/null） */
    private String rootCause;

    /** 根因原文依据 */
    private String rootCauseEvidence;

    /** 验证方式/结果 */
    private String verification;

    /** 验证依据原文 */
    private String verificationEvidence;

    /** 被排除假设 [{hypothesis,evidence}] */
    private List<Map<String, String>> excludedHypotheses;

    /** 适用条件 [{type,value}]，type 五类之一 */
    private List<Map<String, String>> applyConditions;

    /** 条件扁平键，检索/过滤用，如 device_model=LAM-600|process_stage=贴合 */
    private String conditionKeys;

    /** 是否有最终根因 */
    private Boolean hasFinalRootCause;

    /** 三步链式 trace（JSON 字符串；单轮模式为 null） */
    private String chainTrace;

    /** 链式模式是否发生降级（任一步 JSON/校验失败而字段置空） */
    private Boolean chainDegraded;

    /** 降级步骤说明，如 ["step2:no_json"] */
    private List<String> chainErrors;

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
