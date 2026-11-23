package com.tims.ai.apikey;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.math.BigDecimal;
import java.time.LocalDateTime;

/** 管理员填写的租户额度（元）；官方无余额接口时用于本地估算剩余 */
@TableName("ai_tenant_quota")
public class TenantQuota {

    @TableId(type = IdType.INPUT)
    private Long tenantId;

    private BigDecimal quotaCny;

    private Long updatedBy;

    private LocalDateTime updateTime;

    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public BigDecimal getQuotaCny() { return quotaCny; }
    public void setQuotaCny(BigDecimal quotaCny) { this.quotaCny = quotaCny; }
    public Long getUpdatedBy() { return updatedBy; }
    public void setUpdatedBy(Long updatedBy) { this.updatedBy = updatedBy; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
