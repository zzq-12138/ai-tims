package com.tims.knowledge.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableField;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/**
 * M6 AI 知识抽取中间表（工单关闭 → 抽取 → 审核 → 知识库）。
 * 唯一键 (tenant_id, source_ticket_id) 保证同一工单重复消息不产生重复条目。
 * dedupAction 仅为“建议”（NEW/MERGE/SKIP），最终处置必须由审核人点击确认，绝不自动合并。
 */
@TableName("ai_extracted")
public class AiExtracted {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    private Long sourceTicketId;

    private String sourceTicketNo;

    private String sourceTitle;

    private String sourceDeviceType;

    private String title;

    private String deviceType;

    private String faultPhenomenon;

    private String troubleshootSteps;

    private String solutionSteps;

    /** JSON 数组字符串 */
    private String tags;

    private String keyPoints;

    /** 建议结论：NEW 建议新建 / MERGE 建议合并 / SKIP 建议跳过（非执行动作） */
    private String dedupAction;

    private Long dedupTargetId;

    private BigDecimal dedupScore;

    /** 相似度与关键差异摘要，供审核人判断 */
    private String dedupNote;

    /** PENDING_REVIEW / MANUAL_REQUIRED / APPROVED / MERGED / REJECTED */
    private String status;

    private String model;

    private String errorMsg;

    private Long knowledgeId;

    private Long reviewBy;

    private LocalDateTime reviewTime;

    private String rejectReason;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;

    @TableLogic
    @JsonProperty(access = JsonProperty.Access.WRITE_ONLY)
    private Integer deleted;

    /** 相似目标条目标题（非表字段，分页回填便于审核中心展示） */
    @TableField(exist = false)
    private String dedupTargetTitle;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public Long getSourceTicketId() { return sourceTicketId; }
    public void setSourceTicketId(Long sourceTicketId) { this.sourceTicketId = sourceTicketId; }
    public String getSourceTicketNo() { return sourceTicketNo; }
    public void setSourceTicketNo(String sourceTicketNo) { this.sourceTicketNo = sourceTicketNo; }
    public String getSourceTitle() { return sourceTitle; }
    public void setSourceTitle(String sourceTitle) { this.sourceTitle = sourceTitle; }
    public String getSourceDeviceType() { return sourceDeviceType; }
    public void setSourceDeviceType(String sourceDeviceType) { this.sourceDeviceType = sourceDeviceType; }
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
    public String getTags() { return tags; }
    public void setTags(String tags) { this.tags = tags; }
    public String getKeyPoints() { return keyPoints; }
    public void setKeyPoints(String keyPoints) { this.keyPoints = keyPoints; }
    public String getDedupAction() { return dedupAction; }
    public void setDedupAction(String dedupAction) { this.dedupAction = dedupAction; }
    public Long getDedupTargetId() { return dedupTargetId; }
    public void setDedupTargetId(Long dedupTargetId) { this.dedupTargetId = dedupTargetId; }
    public BigDecimal getDedupScore() { return dedupScore; }
    public void setDedupScore(BigDecimal dedupScore) { this.dedupScore = dedupScore; }
    public String getDedupNote() { return dedupNote; }
    public void setDedupNote(String dedupNote) { this.dedupNote = dedupNote; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public String getErrorMsg() { return errorMsg; }
    public void setErrorMsg(String errorMsg) { this.errorMsg = errorMsg; }
    public Long getKnowledgeId() { return knowledgeId; }
    public void setKnowledgeId(Long knowledgeId) { this.knowledgeId = knowledgeId; }
    public Long getReviewBy() { return reviewBy; }
    public void setReviewBy(Long reviewBy) { this.reviewBy = reviewBy; }
    public LocalDateTime getReviewTime() { return reviewTime; }
    public void setReviewTime(LocalDateTime reviewTime) { this.reviewTime = reviewTime; }
    public String getRejectReason() { return rejectReason; }
    public void setRejectReason(String rejectReason) { this.rejectReason = rejectReason; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
    public Integer getDeleted() { return deleted; }
    public void setDeleted(Integer deleted) { this.deleted = deleted; }
    public String getDedupTargetTitle() { return dedupTargetTitle; }
    public void setDedupTargetTitle(String dedupTargetTitle) { this.dedupTargetTitle = dedupTargetTitle; }
}
