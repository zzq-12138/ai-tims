package com.tims.ai.prompt;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/**
 * prompt 版本存档：每次调用记录 prompt_version，可按版本反查当时的内容。
 */
@TableName("ai_prompt_version")
public class AiPromptVersion {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    /** 场景：CHAT / ASSISTANT / AGENT */
    private String scene;

    private String version;

    private String content;

    private Boolean active;

    private Long createdBy;

    private LocalDateTime createTime;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public String getScene() { return scene; }
    public void setScene(String scene) { this.scene = scene; }
    public String getVersion() { return version; }
    public void setVersion(String version) { this.version = version; }
    public String getContent() { return content; }
    public void setContent(String content) { this.content = content; }
    public Boolean getActive() { return active; }
    public void setActive(Boolean active) { this.active = active; }
    public Long getCreatedBy() { return createdBy; }
    public void setCreatedBy(Long createdBy) { this.createdBy = createdBy; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
