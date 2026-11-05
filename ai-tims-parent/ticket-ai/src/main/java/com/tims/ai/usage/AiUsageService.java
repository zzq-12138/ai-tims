package com.tims.ai.usage;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.tims.ai.config.AiProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 调用观测：落库 + 最近 N 次 + 汇总。落库失败绝不阻断 AI 回答。
 *
 * 问题9：智谱开放平台未提供余额/额度查询 API（实测 /balance、/usage、/quota 均 404，
 * 官方文档只给出控制台“用量统计/财务总览”），因此这里做本地计量：
 *   费用 = Σ(promptTokens/1000 × 输入单价) + Σ(completionTokens/1000 × 输出单价)
 *   剩余 = 配置预算 - 费用，全部按“估算”展示，不冒充官方余额。
 */
@Service
public class AiUsageService {

    private static final Logger log = LoggerFactory.getLogger(AiUsageService.class);

    private final AiCallLogMapper mapper;
    private final AiProperties props;

    public AiUsageService(AiCallLogMapper mapper, AiProperties props) {
        this.mapper = mapper;
        this.props = props;
    }

    public void record(AiCallLog row) {
        try {
            if (row.getCreateTime() == null) {
                row.setCreateTime(LocalDateTime.now());
            }
            if (row.getTenantId() == null) {
                row.setTenantId(1L);
            }
            mapper.insert(row);
        } catch (Exception e) {
            log.warn("[usage] 观测落库失败（不影响回答）: {}", e.getMessage());
        }
    }

    /** 最近 N 次调用（租户隔离） */
    public List<AiCallLog> recent(Long tenantId, int limit) {
        int n = Math.max(1, Math.min(limit, 100));
        LambdaQueryWrapper<AiCallLog> q = new LambdaQueryWrapper<>();
        q.eq(AiCallLog::getTenantId, tenantId == null ? 1L : tenantId)
                .orderByDesc(AiCallLog::getCreateTime)
                .last("LIMIT " + n);
        return mapper.selectList(q);
    }

    /** 累计用量 + 估算费用 + 按场景/模型拆分 + 近 7 天走势（全部来自 ai_call_log 实测数据） */
    public Map<String, Object> summary(Long tenantId) {
        Long tid = tenantId == null ? 1L : tenantId;
        QueryWrapper<AiCallLog> q = new QueryWrapper<AiCallLog>()
                .select("COUNT(*) AS calls",
                        "COALESCE(SUM(prompt_tokens),0) AS promptTokens",
                        "COALESCE(SUM(completion_tokens),0) AS completionTokens",
                        "COALESCE(SUM(total_tokens),0) AS totalTokens",
                        "COALESCE(SUM(reasoning_tokens),0) AS reasoningTokens")
                .eq("tenant_id", tid);
        Map<String, Object> total = new LinkedHashMap<>();
        List<Map<String, Object>> rows = mapper.selectMaps(q);
        if (!rows.isEmpty()) {
            total.putAll(rows.get(0));
        }

        QueryWrapper<AiCallLog> err = new QueryWrapper<AiCallLog>()
                .select("COUNT(*) AS errorCalls")
                .eq("tenant_id", tid)
                .eq("status", "ERROR");
        List<Map<String, Object>> errRows = mapper.selectMaps(err);
        total.put("errorCalls", errRows.isEmpty() ? 0 : errRows.get(0).get("errorCalls"));

        QueryWrapper<AiCallLog> tool = new QueryWrapper<AiCallLog>()
                .select("COUNT(*) AS toolCalls")
                .eq("tenant_id", tid)
                .eq("scene", "AGENT_TOOL");
        List<Map<String, Object>> toolRows = mapper.selectMaps(tool);
        total.put("toolCalls", toolRows.isEmpty() ? 0 : toolRows.get(0).get("toolCalls"));

        // 按场景拆分
        QueryWrapper<AiCallLog> byScene = new QueryWrapper<AiCallLog>()
                .select("scene AS scene", "COUNT(*) AS calls", "COALESCE(SUM(total_tokens),0) AS tokens")
                .eq("tenant_id", tid)
                .groupBy("scene")
                .orderByDesc("tokens");
        total.put("byScene", mapper.selectMaps(byScene));

        // 按模型拆分
        QueryWrapper<AiCallLog> byModel = new QueryWrapper<AiCallLog>()
                .select("model AS model", "COUNT(*) AS calls", "COALESCE(SUM(total_tokens),0) AS tokens")
                .eq("tenant_id", tid)
                .isNotNull("model")
                .ne("model", "")
                .groupBy("model")
                .orderByDesc("tokens");
        total.put("byModel", mapper.selectMaps(byModel));

        // 近 7 天走势（按天聚合，仅返回有调用的日期）
        QueryWrapper<AiCallLog> daily = new QueryWrapper<AiCallLog>()
                .select("DATE(create_time) AS day", "COUNT(*) AS calls", "COALESCE(SUM(total_tokens),0) AS tokens")
                .eq("tenant_id", tid)
                .ge("create_time", LocalDate.now().minusDays(6).atStartOfDay())
                .groupBy("day")
                .orderByAsc("day");
        total.put("daily", mapper.selectMaps(daily));

        // 本地估算预算（无官方余额接口）
        long prompt = num(total.get("promptTokens"));
        long completion = num(total.get("completionTokens"));
        double pIn = props.getPriceInputPer1k();
        double pOut = props.getPriceOutputPer1k();
        double cost = prompt / 1000.0 * pIn + completion / 1000.0 * pOut;
        double budget = props.getBudgetCny();
        double remaining = Math.max(0.0, budget - cost);
        total.put("budgetCny", round(budget, 4));
        total.put("priceInputPer1k", round(pIn, 6));
        total.put("priceOutputPer1k", round(pOut, 6));
        total.put("estimatedCostCny", round(cost, 4));
        total.put("remainingCny", round(remaining, 4));
        total.put("usedPercent", budget <= 0 ? 0.0 : round(Math.min(100.0, cost / budget * 100.0), 2));
        total.put("balanceSource", "LOCAL_ESTIMATE");
        total.put("balanceApiAvailable", false);
        return total;
    }

    private long num(Object v) {
        if (v == null) {
            return 0L;
        }
        if (v instanceof BigDecimal bd) {
            return bd.longValue();
        }
        if (v instanceof Number n) {
            return n.longValue();
        }
        try {
            return Long.parseLong(String.valueOf(v));
        } catch (NumberFormatException e) {
            return 0L;
        }
    }

    private double round(double v, int scale) {
        return new BigDecimal(v).setScale(scale, RoundingMode.HALF_UP).doubleValue();
    }
}
