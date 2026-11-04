package com.tims.ai.dto;

import java.util.List;

/**
 * 结构化知识抽取结果（M6）。
 * 标题/设备类型/故障现象/排查步骤/解决步骤/标签/关键要点，统一由 GLM 输出后解析。
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
}
