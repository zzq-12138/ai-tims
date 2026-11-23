package com.tims.ai.controller;

import com.tims.ai.apikey.ApiKeyAudit;
import com.tims.ai.apikey.ApiKeyService;
import com.tims.ai.config.AiProperties;
import com.tims.ai.util.AdminGuard;
import com.tims.ai.util.CurrentUser;
import com.tims.ai.usage.AiUsageService;
import com.tims.common.api.Result;
import com.tims.common.exception.BizException;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 管理员 Key 与额度管理（全部接口要求 ADMIN）：
 * GET    /api/ai/admin/keys                    列表（只回显尾号）
 * POST   /api/ai/admin/keys                    新增/更新（加密落库，改完即生效）
 * DELETE /api/ai/admin/keys/{id}
 * GET    /api/ai/admin/keys/{id}/reveal        查看明文（写 VIEW 审计）
 * GET    /api/ai/admin/keys/quota              租户额度
 * PUT    /api/ai/admin/keys/quota              设置租户额度
 * GET    /api/ai/admin/keys/audits             审计日志
 * GET    /api/ai/admin/keys/balance            余额展示（无官方接口时明确标注估算）
 */
@RestController
@RequestMapping("/api/ai/admin/keys")
public class ApiKeyController {

    private final ApiKeyService apiKeyService;
    private final AiUsageService usageService;
    private final AiProperties props;

    public ApiKeyController(ApiKeyService apiKeyService, AiUsageService usageService, AiProperties props) {
        this.apiKeyService = apiKeyService;
        this.usageService = usageService;
        this.props = props;
    }

    @GetMapping
    public Result<Map<String, Object>> list() {
        AdminGuard.requireAdmin();
        Long tid = CurrentUser.tenantId();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("tenantId", tid);
        out.put("defaultModel", props.getModel());
        out.put("keys", apiKeyService.list(tid));
        out.put("quotaCny", apiKeyService.quota(tid));
        out.put("fallbackNote", "未配置租户 Key 时回落到 application.yml / 环境变量 LLM_API_KEY，行为不变");
        return Result.ok(out);
    }

    @PostMapping
    public Result<Map<String, Object>> save(@RequestBody Map<String, String> body) {
        AdminGuard.requireAdmin();
        Long tid = CurrentUser.tenantId();
        return Result.ok(apiKeyService.save(tid, body.get("provider"), body.get("model"),
                body.get("apiKey"), CurrentUser.id()));
    }

    @DeleteMapping("/{id}")
    public Result<Map<String, Object>> delete(@PathVariable Long id) {
        AdminGuard.requireAdmin();
        apiKeyService.delete(CurrentUser.tenantId(), id, CurrentUser.id());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("deleted", true);
        out.put("id", id);
        return Result.ok(out);
    }

    @GetMapping("/{id}/reveal")
    public Result<Map<String, Object>> reveal(@PathVariable Long id) {
        AdminGuard.requireAdmin();
        return Result.ok(apiKeyService.reveal(CurrentUser.tenantId(), id, CurrentUser.id()));
    }

    @GetMapping("/quota")
    public Result<Map<String, Object>> quota() {
        AdminGuard.requireAdmin();
        Long tid = CurrentUser.tenantId();
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("tenantId", tid);
        out.put("quotaCny", apiKeyService.quota(tid));
        out.put("configured", apiKeyService.list(tid).size() > 0);
        return Result.ok(out);
    }

    @PutMapping("/quota")
    public Result<Map<String, Object>> setQuota(@RequestBody Map<String, Object> body) {
        AdminGuard.requireAdmin();
        Long tid = CurrentUser.tenantId();
        Object raw = body.get("quotaCny");
        BigDecimal quota;
        try {
            quota = new BigDecimal(String.valueOf(raw));
        } catch (Exception e) {
            throw new BizException(40001, "quotaCny 必须为数字");
        }
        apiKeyService.setQuota(tid, quota, CurrentUser.id());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("tenantId", tid);
        out.put("quotaCny", quota);
        return Result.ok(out);
    }

    @GetMapping("/audits")
    public Result<List<ApiKeyAudit>> audits(@RequestParam(defaultValue = "50") int limit) {
        AdminGuard.requireAdmin();
        return Result.ok(apiKeyService.audits(CurrentUser.tenantId(), limit));
    }

    /**
     * 余额展示。智谱开放平台未提供余额/资源包查询 API（/balance、/usage、/quota 均 404），
     * 因此只展示「本地累计消耗 + 管理员填写额度」，并显式标注为估算值，不伪造官方余额。
     */
    @GetMapping("/balance")
    public Result<Map<String, Object>> balance() {
        AdminGuard.requireAdmin();
        Long tid = CurrentUser.tenantId();
        Map<String, Object> summary = usageService.summary(tid);
        BigDecimal quota = apiKeyService.quota(tid);
        BigDecimal consumed = decimal(summary.get("estimatedCostCny"));
        BigDecimal remaining = quota.subtract(consumed);
        if (remaining.signum() < 0) {
            remaining = BigDecimal.ZERO;
        }
        BigDecimal usedPercent = quota.signum() <= 0 ? BigDecimal.ZERO
                : consumed.multiply(BigDecimal.valueOf(100)).divide(quota, 2, RoundingMode.HALF_UP);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("official", false);
        out.put("officialAvailable", false);
        out.put("source", "LOCAL_ESTIMATE");
        out.put("estimate", true);
        out.put("checkedAt", LocalDateTime.now());
        out.put("quotaCny", quota.setScale(4, RoundingMode.HALF_UP));
        out.put("estimatedCostCny", consumed.setScale(4, RoundingMode.HALF_UP));
        out.put("remainingCny", remaining.setScale(4, RoundingMode.HALF_UP));
        out.put("usedPercent", usedPercent.doubleValue());
        out.put("note", "智谱未开放余额/资源包查询接口，本页为本地累计消耗与管理员额度之差，非官方余量");
        out.put("probe", List.of(
                Map.of("path", "/api/paas/v4/balance", "result", "404"),
                Map.of("path", "/api/paas/v4/usage", "result", "404"),
                Map.of("path", "/api/paas/v4/quota", "result", "404")));
        return Result.ok(out);
    }

    private BigDecimal decimal(Object v) {
        if (v == null) {
            return BigDecimal.ZERO;
        }
        if (v instanceof BigDecimal bd) {
            return bd;
        }
        try {
            return new BigDecimal(String.valueOf(v));
        } catch (NumberFormatException e) {
            return BigDecimal.ZERO;
        }
    }
}
