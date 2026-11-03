package com.tims.ai.usage;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 调用观测：落库 + 最近 N 次 + 汇总。落库失败绝不阻断 AI 回答。
 */
@Service
public class AiUsageService {

    private static final Logger log = LoggerFactory.getLogger(AiUsageService.class);

    private final AiCallLogMapper mapper;

    public AiUsageService(AiCallLogMapper mapper) {
        this.mapper = mapper;
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

    /** 累计用量（用于估算配额） */
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
        return total;
    }
}
