package com.tims.knowledge.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/**
 * 知识条目历史快照（M6）。
 * 人工确认“合并”前先写入被合并原条目的完整快照（版本/标题/正文/标签/摘要），
 * 保证合并有据可查、不静默覆盖；changeType 记录 MERGE 合并来源或 UPDATE 手工修改。
 */
@TableName("kb_knowledge_history")
public class KbKnowledgeHistory {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    private Long knowledgeId;

    private Integer version;

    private String title;

    private String content;

    private String summary;

    private String tags;

    private String applyDeviceType;

    /** MERGE / UPDATE / ROLLBACK */
    private String changeType;

    private Long sourceExtractedId;

    private Long createBy;

    private LocalDateTime createTime;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public Long getKnowledgeId() { return knowledgeId; }
    public void setKnowledgeId(Long knowledgeId) { this.knowledgeId = knowledgeId; }
    public Integer getVersion() { return version; }
    public void setVersion(Integer version) { this.version = version; }
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
    public String getChangeType() { return changeType; }
    public void setChangeType(String changeType) { this.changeType = changeType; }
    public Long getSourceExtractedId() { return sourceExtractedId; }
    public void setSourceExtractedId(Long sourceExtractedId) { this.sourceExtractedId = sourceExtractedId; }
    public Long getCreateBy() { return createBy; }
    public void setCreateBy(Long createBy) { this.createBy = createBy; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
