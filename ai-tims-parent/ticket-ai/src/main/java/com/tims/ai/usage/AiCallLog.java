package com.tims.ai.usage;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/**
 * AI 调用观测（M5）：每次 LLM/工具调用落一行，用于估算 ¥18 配额余量与排查。
 * 所有业务表必须带 tenant_id（项目硬约束）。
 */
@TableName("ai_call_log")
public class AiCallLog {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    /** CHAT_STREAM / CHAT_SYNC / AGENT / AGENT_TOOL */
    private String scene;

    private String model;

    /** 工具名（scene=AGENT_TOOL 时记录） */
    private String toolName;

    /** 工具入参摘要（截断存储） */
    private String toolArgs;

    private Integer promptTokens;

    private Integer completionTokens;

    private Integer totalTokens;

    private Integer reasoningTokens;

    /** 总耗时 ms */
    private Long latencyMs;

    /** 首 Token 耗时 ms（流式；工具行为工具耗时） */
    private Long firstTokenMs;

    /** 引用知识条目数 */
    private Integer refCount;

    /** SUCCESS / ERROR / DEGRADED */
    private String status;

    private Boolean degraded;

    private String errorMsg;

    private Long userId;

    private LocalDateTime createTime;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public String getScene() { return scene; }
    public void setScene(String scene) { this.scene = scene; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public String getToolName() { return toolName; }
    public void setToolName(String toolName) { this.toolName = toolName; }
    public String getToolArgs() { return toolArgs; }
    public void setToolArgs(String toolArgs) { this.toolArgs = toolArgs; }
    public Integer getPromptTokens() { return promptTokens; }
    public void setPromptTokens(Integer promptTokens) { this.promptTokens = promptTokens; }
    public Integer getCompletionTokens() { return completionTokens; }
    public void setCompletionTokens(Integer completionTokens) { this.completionTokens = completionTokens; }
    public Integer getTotalTokens() { return totalTokens; }
    public void setTotalTokens(Integer totalTokens) { this.totalTokens = totalTokens; }
    public Integer getReasoningTokens() { return reasoningTokens; }
    public void setReasoningTokens(Integer reasoningTokens) { this.reasoningTokens = reasoningTokens; }
    public Long getLatencyMs() { return latencyMs; }
    public void setLatencyMs(Long latencyMs) { this.latencyMs = latencyMs; }
    public Long getFirstTokenMs() { return firstTokenMs; }
    public void setFirstTokenMs(Long firstTokenMs) { this.firstTokenMs = firstTokenMs; }
    public Integer getRefCount() { return refCount; }
    public void setRefCount(Integer refCount) { this.refCount = refCount; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public Boolean getDegraded() { return degraded; }
    public void setDegraded(Boolean degraded) { this.degraded = degraded; }
    public String getErrorMsg() { return errorMsg; }
    public void setErrorMsg(String errorMsg) { this.errorMsg = errorMsg; }
    public Long getUserId() { return userId; }
    public void setUserId(Long userId) { this.userId = userId; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
