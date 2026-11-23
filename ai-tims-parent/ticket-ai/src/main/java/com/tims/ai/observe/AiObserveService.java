package com.tims.ai.observe;

import com.baomidou.mybatisplus.core.conditions.query.QueryWrapper;
import com.tims.ai.config.AiProperties;
import com.tims.ai.prompt.AiPromptVersion;
import com.tims.ai.prompt.PromptRegistry;
import com.tims.ai.usage.AiCallLog;
import com.tims.ai.usage.AiCallLogMapper;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 调用观测聚合：按时间/用户/场景/模型过滤，输出调用量、token、费用、P50/P95、
 * 失败与护栏拦截、趋势、分模型/分场景/分用户拆分；单条详情带同 traceId 工具链与 prompt 版本内容。
 * 全部数据来自 ai_call_log，不引入额外埋点。
 */
@Service
public class AiObserveService {

    private static final int LATENCY_SAMPLE_LIMIT = 20000;

    private final AiCallLogMapper mapper;
    private final AiProperties props;
    private final PromptRegistry promptRegistry;

    public AiObserveService(AiCallLogMapper mapper, AiProperties props, PromptRegistry promptRegistry) {
        this.mapper = mapper;
        this.props = props;
        this.promptRegistry = promptRegistry;
    }

    /** 查询过滤条件；时间范围闭区间，其余为精确匹配 */
    public record Filter(LocalDateTime from, LocalDateTime to, Long userId,
                         String scene, String model, String status) { }

    public Map<String, Object> overview(Long tenantId, Filter f) {
        Long tid = tenantId == null ? 1L : tenantId;

        Map<String, Object> total = new LinkedHashMap<>();
        List<Map<String, Object>> rows = mapper.selectMaps(base(tid, f)
                .select("COUNT(*) AS calls",
                        "COALESCE(SUM(prompt_tokens),0) AS promptTokens",
                        "COALESCE(SUM(completion_tokens),0) AS completionTokens",
                        "COALESCE(SUM(total_tokens),0) AS totalTokens",
                        "COALESCE(SUM(reasoning_tokens),0) AS reasoningTokens"));
        if (!rows.isEmpty()) {
            total.putAll(rows.get(0));
        }
        total.put("errorCalls", count(tid, f, q -> q.eq("status", "ERROR")));
        total.put("blockedCalls", count(tid, f, q -> q.eq("guard_blocked", 1)));
        total.put("cacheHitCalls", count(tid, f, q -> q.eq("status", "CACHE_HIT")));
        total.put("toolCalls", count(tid, f, q -> q.eq("scene", "AGENT_TOOL")));

        // 分模型 + 分模型费用
        List<Map<String, Object>> byModel = mapper.selectMaps(base(tid, f)
                .select("model AS model", "COUNT(*) AS calls",
                        "COALESCE(SUM(total_tokens),0) AS tokens",
                        "COALESCE(SUM(prompt_tokens),0) AS promptTokens",
                        "COALESCE(SUM(completion_tokens),0) AS completionTokens")
                .isNotNull("model").ne("model", "")
                .groupBy("model").orderByDesc("tokens"));
        double cost = 0.0;
        for (Map<String, Object> row : byModel) {
            AiProperties.Price price = props.priceOf(str(row.get("model")));
            double c = num(row.get("promptTokens")) / 1000.0 * price.getInputPer1k()
                    + num(row.get("completionTokens")) / 1000.0 * price.getOutputPer1k();
            row.put("estimatedCostCny", round(c, 4));
            row.put("priceInputPer1k", round(price.getInputPer1k(), 6));
            row.put("priceOutputPer1k", round(price.getOutputPer1k(), 6));
            cost += c;
        }
        total.put("byModel", byModel);
        total.put("estimatedCostCny", round(cost, 4));

        total.put("byScene", mapper.selectMaps(base(tid, f)
                .select("scene AS scene", "COUNT(*) AS calls",
                        "COALESCE(SUM(total_tokens),0) AS tokens")
                .groupBy("scene").orderByDesc("calls")));
        total.put("byStatus", mapper.selectMaps(base(tid, f)
                .select("status AS status", "COUNT(*) AS calls")
                .groupBy("status").orderByDesc("calls")));
        total.put("byUser", mapper.selectMaps(base(tid, f)
                .select("user_id AS userId", "COUNT(*) AS calls",
                        "COALESCE(SUM(total_tokens),0) AS tokens")
                .isNotNull("user_id")
                .groupBy("user_id").orderByDesc("calls").last("LIMIT 10")));
        total.put("trend", mapper.selectMaps(base(tid, f)
                .select("DATE_FORMAT(create_time,'%Y-%m-%d') AS day", "COUNT(*) AS calls",
                        "COALESCE(SUM(total_tokens),0) AS tokens")
                .groupBy("day").orderByAsc("day")));

        // 耗时：样本内排序求 P50/P95 + 分桶
        List<Object> latencies = mapper.selectObjs(base(tid, f)
                .select("latency_ms")
                .ne("scene", "AGENT_TOOL")
                .isNotNull("latency_ms")
                .last("LIMIT " + LATENCY_SAMPLE_LIMIT));
        long[] arr = latencies.stream().filter(v -> v instanceof Number)
                .mapToLong(v -> ((Number) v).longValue()).filter(v -> v >= 0).sorted().toArray();
        Map<String, Object> latency = new LinkedHashMap<>();
        latency.put("sampleSize", arr.length);
        latency.put("avgMs", arr.length == 0 ? 0 : Math.round(Arrays.stream(arr).average().orElse(0)));
        latency.put("p50Ms", percentile(arr, 50));
        latency.put("p95Ms", percentile(arr, 95));
        latency.put("maxMs", arr.length == 0 ? 0 : arr[arr.length - 1]);
        latency.put("buckets", buckets(arr));
        total.put("latency", latency);

        total.put("from", f.from());
        total.put("to", f.to());
        total.put("pricingNote", "费用按分模型单价（元/千 tokens）折算，非官方账单");
        return total;
    }

    public Map<String, Object> calls(Long tenantId, Filter f, int page, int size) {
        Long tid = tenantId == null ? 1L : tenantId;
        int p = Math.max(1, page);
        int s = Math.max(1, Math.min(size, 200));
        long total = count(tid, f, q -> { });
        List<AiCallLog> rows = mapper.selectList(base(tid, f)
                .orderByDesc("create_time")
                .last("LIMIT " + s + " OFFSET " + ((long) (p - 1) * s)));
        List<Map<String, Object>> items = new ArrayList<>();
        for (AiCallLog row : rows) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", row.getId());
            m.put("traceId", row.getTraceId());
            m.put("scene", row.getScene());
            m.put("model", row.getModel());
            m.put("userId", row.getUserId());
            m.put("toolName", row.getToolName());
            m.put("toolArgs", row.getToolArgs());
            m.put("promptTokens", row.getPromptTokens());
            m.put("completionTokens", row.getCompletionTokens());
            m.put("totalTokens", row.getTotalTokens());
            m.put("reasoningTokens", row.getReasoningTokens());
            m.put("latencyMs", row.getLatencyMs());
            m.put("firstTokenMs", row.getFirstTokenMs());
            m.put("status", row.getStatus());
            m.put("degraded", row.getDegraded());
            m.put("guardBlocked", row.getGuardBlocked());
            m.put("promptVersion", row.getPromptVersion());
            m.put("errorMsg", row.getErrorMsg());
            m.put("createTime", row.getCreateTime());
            m.put("estimatedCostCny", round(cost(row), 6));
            items.add(m);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("total", total);
        out.put("page", p);
        out.put("size", s);
        out.put("items", items);
        return out;
    }

    public Map<String, Object> detail(Long tenantId, Long id) {
        Long tid = tenantId == null ? 1L : tenantId;
        AiCallLog row = mapper.selectById(id);
        if (row == null || row.getTenantId() == null || !row.getTenantId().equals(tid)) {
            return null;
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("call", row);
        out.put("estimatedCostCny", round(cost(row), 6));

        // 同 traceId 的工具链（父调用 + 工具行）
        List<AiCallLog> chain = new ArrayList<>();
        if (row.getTraceId() != null && !row.getTraceId().isBlank()) {
            chain = mapper.selectList(new QueryWrapper<AiCallLog>()
                    .eq("tenant_id", tid)
                    .eq("trace_id", row.getTraceId())
                    .orderByAsc("create_time"));
        }
        out.put("trace", chain);

        out.put("prompt", promptOf(tid, row));
        return out;
    }

    /** 该次调用使用的 prompt 版本内容（历史版本保留，可直接反查） */
    private Map<String, Object> promptOf(Long tenantId, AiCallLog row) {
        Map<String, Object> p = new LinkedHashMap<>();
        String scene = promptScene(row.getScene());
        p.put("scene", scene);
        p.put("version", row.getPromptVersion());
        p.put("found", false);
        p.put("content", null);
        if (row.getPromptVersion() == null || row.getPromptVersion().isBlank()) {
            p.put("note", "该次调用未记录 prompt 版本");
            return p;
        }
        if ("guard-v1".equals(row.getPromptVersion())) {
            p.put("note", "护栏拦截记录，无生成 prompt");
            return p;
        }
        try {
            AiPromptVersion v = promptRegistry.byVersion(tenantId, scene, row.getPromptVersion());
            if (v != null) {
                p.put("found", true);
                p.put("content", v.getContent());
                p.put("active", v.getActive());
                p.put("createTime", v.getCreateTime());
            } else {
                p.put("note", "版本存档不存在（可能已清理）");
            }
        } catch (Exception e) {
            p.put("note", "版本存档不可用：" + e.getMessage());
        }
        return p;
    }

    private String promptScene(String scene) {
        if (scene == null) {
            return "CHAT";
        }
        return scene.startsWith("AGENT") ? "ASSISTANT" : "CHAT";
    }

    private QueryWrapper<AiCallLog> base(Long tenantId, Filter f) {
        QueryWrapper<AiCallLog> q = new QueryWrapper<>();
        q.eq("tenant_id", tenantId);
        if (f != null) {
            if (f.from() != null) {
                q.ge("create_time", f.from());
            }
            if (f.to() != null) {
                q.le("create_time", f.to());
            }
            if (f.userId() != null) {
                q.eq("user_id", f.userId());
            }
            if (text(f.scene())) {
                q.eq("scene", f.scene());
            }
            if (text(f.model())) {
                q.eq("model", f.model());
            }
            if (text(f.status())) {
                q.eq("status", f.status());
            }
        }
        return q;
    }

    private long count(Long tenantId, Filter f, java.util.function.Consumer<QueryWrapper<AiCallLog>> extra) {
        QueryWrapper<AiCallLog> q = base(tenantId, f).select("COUNT(*) AS c");
        extra.accept(q);
        List<Map<String, Object>> rows = mapper.selectMaps(q);
        return rows.isEmpty() ? 0 : num(rows.get(0).get("c"));
    }

    private double cost(AiCallLog row) {
        AiProperties.Price p = props.priceOf(row.getModel());
        return num(row.getPromptTokens()) / 1000.0 * p.getInputPer1k()
                + num(row.getCompletionTokens()) / 1000.0 * p.getOutputPer1k();
    }

    private List<Map<String, Object>> buckets(long[] sorted) {
        long[] edges = {0, 500, 1000, 2000, 5000, Long.MAX_VALUE};
        String[] labels = {"<500ms", "500-1000ms", "1-2s", "2-5s", ">=5s"};
        long[] counts = new long[labels.length];
        for (long v : sorted) {
            for (int i = 0; i < labels.length; i++) {
                if (v >= edges[i] && v < edges[i + 1]) {
                    counts[i]++;
                    break;
                }
            }
        }
        List<Map<String, Object>> out = new ArrayList<>();
        for (int i = 0; i < labels.length; i++) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("bucket", labels[i]);
            m.put("calls", counts[i]);
            out.add(m);
        }
        return out;
    }

    private long percentile(long[] sorted, int p) {
        if (sorted.length == 0) {
            return 0;
        }
        int idx = (int) Math.ceil(p / 100.0 * sorted.length) - 1;
        idx = Math.max(0, Math.min(idx, sorted.length - 1));
        return sorted[idx];
    }

    private static String str(Object v) {
        return v == null ? "" : String.valueOf(v);
    }

    private static boolean text(String s) {
        return s != null && !s.isBlank();
    }

    private static long num(Object v) {
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

    private static double round(double v, int scale) {
        return new BigDecimal(v).setScale(scale, RoundingMode.HALF_UP).doubleValue();
    }
}
