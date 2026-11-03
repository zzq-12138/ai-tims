package com.tims.knowledge.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableLogic;
import com.baomidou.mybatisplus.annotation.TableName;
import com.fasterxml.jackson.annotation.JsonProperty;

import java.time.LocalDateTime;

/**
 * 知识点主表（M3）。tags 为 JSON 数组字符串（前端传 JSON 文本，原样入库）。
 * 状态机：DRAFT → PENDING → PUBLISHED / REJECTED（REJECTED 可改后重新提交）。
 * 注：项目约定不使用 Lombok，getter/setter 手写（与 ticket-order 同口径）。
 */
@TableName("kb_knowledge")
public class KbKnowledge {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    private String title;

    private String content;

    private String summary;

    /** JSON 数组字符串，如 ["贴片机","抛料"] */
    private String tags;

    private String applyDeviceType;

    private Long categoryId;

    private Long sourceTicketId;

    private String status;

    private String rejectReason;

    private Integer version;

    private Integer quoteCount;

    private Long createBy;

    private LocalDateTime vectorSyncedAt;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;

    @TableLogic
    @JsonProperty(access = JsonProperty.Access.WRITE_ONLY)
    private Integer deleted;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public String getSummary() { return summary; }
    public void setSummary(String summary) { this.summary = summary; }
    public String getTags() { return tags; }
    public void setTags(String tags) { this.tags = tags; }
    public String getApplyDeviceType() { return applyDeviceType; }
    public void setApplyDeviceType(String applyDeviceType) { this.applyDeviceType = applyDeviceType; }
    public Long getCategoryId() { return categoryId; }
    public void setCategoryId(Long categoryId) { this.categoryId = categoryId; }
    public Long getSourceTicketId() { return sourceTicketId; }
    public void setSourceTicketId(Long sourceTicketId) { this.sourceTicketId = sourceTicketId; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getRejectReason() { return rejectReason; }
    public void setRejectReason(String rejectReason) { this.rejectReason = rejectReason; }
    public Integer getVersion() { return version; }
    public void setVersion(Integer version) { this.version = version; }
    public Integer getQuoteCount() { return quoteCount; }
    public void setQuoteCount(Integer quoteCount) { this.quoteCount = quoteCount; }
    public Long getCreateBy() { return createBy; }
    public void setCreateBy(Long createBy) { this.createBy = createBy; }
    public LocalDateTime getVectorSyncedAt() { return vectorSyncedAt; }
    public void setVectorSyncedAt(LocalDateTime vectorSyncedAt) { this.vectorSyncedAt = vectorSyncedAt; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
    public Integer getDeleted() { return deleted; }
    public void setDeleted(Integer deleted) { this.deleted = deleted; }
}
