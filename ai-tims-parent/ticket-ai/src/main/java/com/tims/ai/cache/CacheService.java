package com.tims.ai.cache;

import com.tims.ai.apikey.AiTenantContext;
import com.tims.ai.rag.KbRef;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Map;
import java.util.Optional;

/**
 * 语义缓存编排：查（精确 → 向量相似）→ 未命中则把本次答案写回。
 * 任何异常/超时都按未命中处理，绝不阻断问答。
 */
@Service
public class CacheService {

    /** 命中结果（供 Controller/VO 展示） */
    public record Hit(String answer, List<KbRef> refs, double similarity, boolean exact,
                      String matchedQuestion, long ageSeconds) { }

    /** 一次请求的探测结果：未命中时携带向量，写回时复用，避免重复调用 embedding */
    public record Probe(String normQuestion, double[] vector, Hit result) {
        public boolean isHit() { return result != null; }
    }

    private final CacheProperties props;
    private final SemanticCache cache;
    private final EmbeddingClient embeddingClient;

    public CacheService(CacheProperties props, SemanticCache cache, EmbeddingClient embeddingClient) {
        this.props = props;
        this.cache = cache;
        this.embeddingClient = embeddingClient;
    }

    public boolean enabled() {
        return props.isEnabled();
    }

    public double threshold() {
        return props.getThreshold();
    }

    /**
     * 查询缓存。未启用/问题过短直接返回“无命中”；embedding 失败时退化为仅精确匹配。
     *
     * @param question 已脱敏的问题文本
     * @param scope    检索上下文指纹（租户内同工单/同知识引用/同历史才算同桶）
     */
    public Probe probe(Long tenantId, String question, String scope, String model) {
        if (!props.isEnabled() || question == null || question.strip().length() < props.getMinQuestionChars()) {
            return new Probe("", null, null);
        }
        String norm = SemanticCache.normalize(question);
        Optional<SemanticCache.Match> exact = cache.exact(tenantId, scope, model, norm);
        if (exact.isPresent()) {
            return new Probe(norm, exact.get().entry().vector(), toHit(exact.get()));
        }
        double[] vector;
        AiTenantContext.set(tenantId);
        try {
            vector = embeddingClient.embed(question);
        } finally {
            AiTenantContext.clear();
        }
        if (vector == null) {
            return new Probe(norm, null, null);
        }
        Optional<SemanticCache.Match> near = cache.nearest(tenantId, scope, model, vector, props.getThreshold());
        return new Probe(norm, vector, near.map(this::toHit).orElse(null));
    }

    /** 写回（仅未命中时调用；答案为空/被护栏拦截时由调用方决定不写） */
    public void put(Long tenantId, String scope, String model, Probe probe,
                    String question, String answer, List<KbRef> refs) {
        if (!props.isEnabled() || probe == null || probe.isHit() || answer == null || answer.isBlank()) {
            return;
        }
        if (question == null || question.strip().length() < props.getMinQuestionChars()) {
            return;
        }
        cache.put(tenantId, scope, model, probe.normQuestion(), question, probe.vector(),
                answer, refs, props.getTtlSeconds(), props.getMaxEntries());
    }

    public Map<String, Object> stats() {
        Map<String, Object> m = cache.stats();
        m.put("enabled", props.isEnabled());
        m.put("threshold", props.getThreshold());
        m.put("embeddingModel", props.getEmbeddingModel());
        m.put("ttlSeconds", props.getTtlSeconds());
        m.put("maxEntries", props.getMaxEntries());
        return m;
    }

    private Hit toHit(SemanticCache.Match m) {
        return new Hit(m.entry().answer(), m.entry().refs(), round(m.similarity()), m.exact(),
                m.entry().question(), Math.max(0, (System.currentTimeMillis() - m.entry().createdAt()) / 1000));
    }

    private static double round(double v) {
        return Math.round(v * 10_000.0) / 10_000.0;
    }
}
