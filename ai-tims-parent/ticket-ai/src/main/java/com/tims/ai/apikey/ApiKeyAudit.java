package com.tims.ai.apikey;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/** Key 管理审计：创建/更新/删除/查看都留痕，不记录明文 */
@TableName("ai_key_audit")
public class ApiKeyAudit {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    /** CREATE / UPDATE / DELETE / VIEW */
    private String action;

    private String provider;

    private String model;

    private String keyTail;

    private Long operatorId;

    private String detail;

    private LocalDateTime createTime;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public String getAction() { return action; }
    public void setAction(String action) { this.action = action; }
    public String getProvider() { return provider; }
    public void setProvider(String provider) { this.provider = provider; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public String getKeyTail() { return keyTail; }
    public void setKeyTail(String keyTail) { this.keyTail = keyTail; }
    public Long getOperatorId() { return operatorId; }
    public void setOperatorId(Long operatorId) { this.operatorId = operatorId; }
    public String getDetail() { return detail; }
    public void setDetail(String detail) { this.detail = detail; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
}
