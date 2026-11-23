package com.tims.ai.apikey;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/** 租户级模型 Key（密文存储，列表只回显尾号） */
@TableName("ai_tenant_key")
public class TenantApiKey {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    private String provider;

    /** 模型名（展示/对账用；实际模型由 tims.ai 配置或路由决定） */
    private String model;

    private String apiKeyCipher;

    private String keyTail;

    private Long updatedBy;

    private LocalDateTime updateTime;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public String getProvider() { return provider; }
    public void setProvider(String provider) { this.provider = provider; }
    public String getModel() { return model; }
    public void setModel(String model) { this.model = model; }
    public String getApiKeyCipher() { return apiKeyCipher; }
    public void setApiKeyCipher(String apiKeyCipher) { this.apiKeyCipher = apiKeyCipher; }
    public String getKeyTail() { return keyTail; }
    public void setKeyTail(String keyTail) { this.keyTail = keyTail; }
    public Long getUpdatedBy() { return updatedBy; }
    public void setUpdatedBy(Long updatedBy) { this.updatedBy = updatedBy; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
