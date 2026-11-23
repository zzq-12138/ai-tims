package com.tims.ai.apikey;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.ai.config.AiProperties;
import com.tims.common.exception.BizException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.math.BigDecimal;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 租户 API Key 管理：
 * - 落库前 AES-GCM 加密，列表只回显尾号；
 * - 修改/删除/查看明文写审计；
 * - 运行时按租户查库解密，改完立即生效（无本地缓存）；
 * - 未配置的租户回落到 application.yml / 环境变量默认 Key。
 */
@Service
public class ApiKeyService {

    private static final Logger log = LoggerFactory.getLogger(ApiKeyService.class);
    private static final String PROVIDER = "zhipu";

    private final TenantApiKeyMapper keyMapper;
    private final TenantQuotaMapper quotaMapper;
    private final ApiKeyAuditMapper auditMapper;
    private final ApiKeyCipher cipher;
    private final AiProperties props;

    public ApiKeyService(TenantApiKeyMapper keyMapper, TenantQuotaMapper quotaMapper,
                         ApiKeyAuditMapper auditMapper, ApiKeyCipher cipher, AiProperties props) {
        this.keyMapper = keyMapper;
        this.quotaMapper = quotaMapper;
        this.auditMapper = auditMapper;
        this.cipher = cipher;
        this.props = props;
    }

    public List<Map<String, Object>> list(Long tenantId) {
        List<TenantApiKey> rows = keyMapper.selectList(new LambdaQueryWrapper<TenantApiKey>()
                .eq(TenantApiKey::getTenantId, tenantId)
                .orderByDesc(TenantApiKey::getUpdateTime));
        List<Map<String, Object>> out = new ArrayList<>();
        for (TenantApiKey k : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", k.getId());
            m.put("provider", k.getProvider());
            m.put("model", k.getModel());
            m.put("keyTail", k.getKeyTail());
            m.put("updatedBy", k.getUpdatedBy());
            m.put("updateTime", k.getUpdateTime());
            // 明确只给尾号，明文不出列表接口
            m.put("masked", "****" + (k.getKeyTail() == null ? "" : k.getKeyTail()));
            out.add(m);
        }
        return out;
    }

    public Map<String, Object> save(Long tenantId, String provider, String model, String apiKey, Long operator) {
        if (!StringUtils.hasText(apiKey)) {
            throw new BizException(40001, "API Key 不能为空");
        }
        String p = StringUtils.hasText(provider) ? provider.trim() : PROVIDER;
        String m = StringUtils.hasText(model) ? model.trim() : props.getModel();
        String key = apiKey.trim();

        TenantApiKey exists = keyMapper.selectOne(new LambdaQueryWrapper<TenantApiKey>()
                .eq(TenantApiKey::getTenantId, tenantId)
                .eq(TenantApiKey::getProvider, p)
                .eq(TenantApiKey::getModel, m)
                .last("LIMIT 1"));
        boolean create = exists == null;
        TenantApiKey row = create ? new TenantApiKey() : exists;
        row.setTenantId(tenantId);
        row.setProvider(p);
        row.setModel(m);
        row.setApiKeyCipher(cipher.encrypt(key));
        row.setKeyTail(ApiKeyCipher.tail(key));
        row.setUpdatedBy(operator);
        row.setUpdateTime(LocalDateTime.now());
        if (create) {
            keyMapper.insert(row);
        } else {
            keyMapper.updateById(row);
        }
        audit(tenantId, create ? "CREATE" : "UPDATE", p, m, row.getKeyTail(), operator,
                "保存模型 Key " + ApiKeyCipher.masked(key));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.getId());
        out.put("provider", p);
        out.put("model", m);
        out.put("keyTail", row.getKeyTail());
        out.put("created", create);
        return out;
    }

    public void delete(Long tenantId, Long id, Long operator) {
        TenantApiKey row = keyMapper.selectOne(new LambdaQueryWrapper<TenantApiKey>()
                .eq(TenantApiKey::getTenantId, tenantId)
                .eq(TenantApiKey::getId, id)
                .last("LIMIT 1"));
        if (row == null) {
            throw new BizException(40401, "Key 不存在");
        }
        keyMapper.deleteById(id);
        audit(tenantId, "DELETE", row.getProvider(), row.getModel(), row.getKeyTail(), operator,
                "删除模型 Key");
    }

    /** 管理员显式查看明文：必须写 VIEW 审计 */
    public Map<String, Object> reveal(Long tenantId, Long id, Long operator) {
        TenantApiKey row = keyMapper.selectOne(new LambdaQueryWrapper<TenantApiKey>()
                .eq(TenantApiKey::getTenantId, tenantId)
                .eq(TenantApiKey::getId, id)
                .last("LIMIT 1"));
        if (row == null) {
            throw new BizException(40401, "Key 不存在");
        }
        String plain = cipher.decrypt(row.getApiKeyCipher());
        if (plain == null) {
            throw new BizException(50001, "解密失败，请重新配置该 Key");
        }
        audit(tenantId, "VIEW", row.getProvider(), row.getModel(), row.getKeyTail(), operator,
                "查看明文");
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", row.getId());
        out.put("apiKey", plain);
        out.put("keyTail", row.getKeyTail());
        out.put("queryTime", LocalDateTime.now());
        return out;
    }

    /** 运行时解析：租户有配置用配置，否则返回 null，由调用方回落到默认 Key */
    public String resolve(Long tenantId) {
        if (tenantId == null) {
            return null;
        }
        try {
            TenantApiKey row = keyMapper.selectOne(new LambdaQueryWrapper<TenantApiKey>()
                    .eq(TenantApiKey::getTenantId, tenantId)
                    .eq(TenantApiKey::getProvider, PROVIDER)
                    .orderByDesc(TenantApiKey::getUpdateTime)
                    .last("LIMIT 1"));
            if (row == null) {
                return null;
            }
            return cipher.decrypt(row.getApiKeyCipher());
        } catch (Exception e) {
            // 表未建/查询失败：回落默认 Key，不影响调用
            log.warn("[apikey] 解析租户 Key 失败，回落默认: {}", e.getMessage());
            return null;
        }
    }

    public BigDecimal quota(Long tenantId) {
        try {
            TenantQuota q = quotaMapper.selectById(tenantId);
            if (q != null && q.getQuotaCny() != null) {
                return q.getQuotaCny();
            }
        } catch (Exception e) {
            log.warn("[apikey] 读取租户额度失败，回落全局预算: {}", e.getMessage());
        }
        return BigDecimal.valueOf(props.getBudgetCny());
    }

    public void setQuota(Long tenantId, BigDecimal quota, Long operator) {
        if (quota == null || quota.signum() < 0) {
            throw new BizException(40001, "额度必须为非负数");
        }
        TenantQuota q = quotaMapper.selectById(tenantId);
        boolean create = q == null;
        if (create) {
            q = new TenantQuota();
            q.setTenantId(tenantId);
        }
        q.setQuotaCny(quota);
        q.setUpdatedBy(operator);
        q.setUpdateTime(LocalDateTime.now());
        if (create) {
            quotaMapper.insert(q);
        } else {
            quotaMapper.updateById(q);
        }
        audit(tenantId, "QUOTA", null, null, null, operator, "设置额度 " + quota + " 元");
    }

    public List<ApiKeyAudit> audits(Long tenantId, int limit) {
        return auditMapper.selectList(new LambdaQueryWrapper<ApiKeyAudit>()
                .eq(ApiKeyAudit::getTenantId, tenantId)
                .orderByDesc(ApiKeyAudit::getCreateTime)
                .last("LIMIT " + Math.max(1, Math.min(limit, 200))));
    }

    private void audit(Long tenantId, String action, String provider, String model,
                       String tail, Long operator, String detail) {
        try {
            ApiKeyAudit a = new ApiKeyAudit();
            a.setTenantId(tenantId);
            a.setAction(action);
            a.setProvider(provider);
            a.setModel(model);
            a.setKeyTail(tail);
            a.setOperatorId(operator);
            a.setDetail(detail);
            a.setCreateTime(LocalDateTime.now());
            auditMapper.insert(a);
        } catch (Exception e) {
            log.error("[apikey] 审计写入失败 action={} tenant={}: {}", action, tenantId, e.getMessage());
        }
    }
}
