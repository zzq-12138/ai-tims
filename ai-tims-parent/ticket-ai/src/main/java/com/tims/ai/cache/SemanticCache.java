package com.tims.ai.cache;

import com.tims.ai.rag.KbRef;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.atomic.LongAdder;

/**
 * 进程内语义缓存：精确 hash + embedding 余弦相似度。
 *
 * 命中前提（key 的组成部分，全部相等才参与相似度比较）：
 *   租户 + 检索上下文指纹 + 模型。
 * 这样避免把 A 工单/别的租户/别的模型上的答案串给当前问题。
 * 单体部署够用；多实例时各实例独立缓存，命中率按实例计（文档已注明局限）。
 */
@Component
public class SemanticCache {

    /** 一条缓存记录；vector 为空表示只支持精确命中（embedding 不可用时降级） */
    public record Entry(String normQuestion, String scope, String model, String question,
                        double[] vector, String answer, List<KbRef> refs,
                        long createdAt, long expiresAt) { }

    /** 命中结果 */
    public record Match(Entry entry, double similarity, boolean exact) { }

    private final ConcurrentHashMap<Long, List<Entry>> byTenant = new ConcurrentHashMap<>();

    private final LongAdder lookupCount = new LongAdder();
    private final LongAdder exactHits = new LongAdder();
    private final LongAdder semanticHits = new LongAdder();

    /** 精确命中（同租户、同上下文、同模型、归一化问题完全一致） */
    public synchronized Optional<Match> exact(Long tenantId, String scope, String model, String normQuestion) {
        lookupCount.increment();
        long now = System.currentTimeMillis();
        for (Entry e : entries(tenantId)) {
            if (e.expiresAt() > now && e.normQuestion().equals(normQuestion)
                    && e.scope().equals(scope) && e.model().equals(model)) {
                exactHits.increment();
                return Optional.of(new Match(e, 1.0, true));
            }
        }
        return Optional.empty();
    }

    /** 语义命中：在与 exact 相同的租户/上下文/模型桶内取余弦最大且 ≥ 阈值者 */
    public synchronized Optional<Match> nearest(Long tenantId, String scope, String model,
                                                 double[] vector, double threshold) {
        if (vector == null) {
            return Optional.empty();
        }
        long now = System.currentTimeMillis();
        Entry best = null;
        double bestSim = -1.0;
        for (Entry e : entries(tenantId)) {
            if (e.expiresAt() <= now || e.vector() == null
                    || !e.scope().equals(scope) || !e.model().equals(model)) {
                continue;
            }
            double sim = cosine(vector, e.vector());
            if (sim > bestSim) {
                bestSim = sim;
                best = e;
            }
        }
        if (best != null && bestSim >= threshold) {
            semanticHits.increment();
            return Optional.of(new Match(best, bestSim, false));
        }
        return Optional.empty();
    }

    /** 写入；同 key 覆盖（问题改写后答案更新时不保留旧值） */
    public synchronized void put(Long tenantId, String scope, String model, String normQuestion,
                                 String question, double[] vector, String answer, List<KbRef> refs,
                                 int ttlSeconds, int maxEntries) {
        if (answer == null || answer.isBlank()) {
            return;
        }
        long now = System.currentTimeMillis();
        List<Entry> list = byTenant.computeIfAbsent(tenantId, k -> new ArrayList<>());
        list.removeIf(e -> e.normQuestion().equals(normQuestion)
                && e.scope().equals(scope) && e.model().equals(model));
        prune(list, now, maxEntries);
        list.add(new Entry(normQuestion, scope, model, truncate(question, 200), vector,
                answer, refs == null ? List.of() : List.copyOf(refs), now, now + ttlSeconds * 1000L));
    }

    public synchronized int size(Long tenantId) {
        return entries(tenantId).size();
    }

    /** 观测用：查询/命中计数 + 各租户条目数 */
    public Map<String, Object> stats() {
        long lookups = lookupCount.sum();
        long exact = exactHits.sum();
        long semantic = semanticHits.sum();
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("lookups", lookups);
        m.put("exactHits", exact);
        m.put("semanticHits", semantic);
        m.put("hits", exact + semantic);
        m.put("hitRate", lookups == 0 ? 0.0 : round(100.0 * (exact + semantic) / lookups));
        Map<String, Integer> sizes = new LinkedHashMap<>();
        byTenant.forEach((t, l) -> sizes.put(String.valueOf(t), l.size()));
        m.put("entriesByTenant", sizes);
        return m;
    }

    /** 问题归一化：小写、全半角标点折叠、去空白，保证“同一句话”能精确命中 */
    public static String normalize(String q) {
        if (q == null) {
            return "";
        }
        String s = q.toLowerCase()
                .replace('，', ',').replace('。', '.').replace('？', '?').replace('！', '!')
                .replace('：', ':').replace('；', ';').replace('、', ',').replace('（', '(')
                .replace('）', ')').replace('　', ' ');
        return s.replaceAll("[\\p{Punct}\\s]+", "").trim();
    }

    private List<Entry> entries(Long tenantId) {
        return byTenant.computeIfAbsent(tenantId == null ? 1L : tenantId, k -> new ArrayList<>());
    }

    private void prune(List<Entry> list, long now, int maxEntries) {
        list.removeIf(e -> e.expiresAt() <= now);
        while (list.size() >= Math.max(1, maxEntries)) {
            Iterator<Entry> it = list.iterator();
            Entry oldest = null;
            while (it.hasNext()) {
                Entry e = it.next();
                if (oldest == null || e.createdAt() < oldest.createdAt()) {
                    oldest = e;
                }
            }
            if (oldest == null) {
                break;
            }
            list.remove(oldest);
        }
    }

    private static double cosine(double[] a, double[] b) {
        if (a == null || b == null || a.length != b.length) {
            return -1.0;
        }
        double dot = 0.0;
        double na = 0.0;
        double nb = 0.0;
        for (int i = 0; i < a.length; i++) {
            dot += a[i] * b[i];
            na += a[i] * a[i];
            nb += b[i] * b[i];
        }
        if (na <= 0 || nb <= 0) {
            return -1.0;
        }
        return dot / (Math.sqrt(na) * Math.sqrt(nb));
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max);
    }

    private static double round(double v) {
        return Math.round(v * 100.0) / 100.0;
    }
}
