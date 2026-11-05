package com.tims.knowledge.service;

import com.tims.common.exception.BizException;
import com.tims.knowledge.entity.KbKnowledge;
import com.tims.knowledge.mapper.KbKnowledgeMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Function;
import java.util.stream.Collectors;

/**
 * 知识检索服务（M3）：三模式 VECTOR / KEYWORD / HYBRID。
 * - KEYWORD：MySQL FULLTEXT（ngram）MATCH...AGAINST，取 Top10；
 * - VECTOR：智谱 embedding-3 → Milvus HNSW/COSINE，取 Top10；
 * - HYBRID：两路各 Top10 → RRF(k=60) 融合 → 设备类型/标签加权 → 输出 Top5。
 * 降级矩阵：Milvus 不可用（isAvailable()=false）或向量检索异常时自动退纯关键词，
 * 返回体带 fallback=true（VECTOR 与 HYBRID 均适用）。
 *
 * M7 追加（B0 基线）：返回体透出原始余弦 vectorScore 与 rrfScore，并新增 kb.gate 三档门控
 * （A=正常推送 / B=软带内仅供参考 / C=低于阈值不返回），tier 与 reason 为新增字段，
 * 老字段（score/items/fallback/total）保持不变。
 */
@Service
public class SearchService {

    private static final Logger log = LoggerFactory.getLogger(SearchService.class);

    /** 两路召回条数（任务书口径：向量 Top10 + 全文 Top10） */
    private static final int CANDIDATE_K = 10;
    /** RRF 常数（论文推荐 60） */
    private static final double RRF_K = 60;
    /** 设备类型命中加权系数 */
    private static final double DEVICE_BOOST = 1.5;
    /** 标签命中加权系数 */
    private static final double TAG_BOOST = 1.2;

    @Value("${tims.kb.gate.enabled:true}")
    private boolean gateEnabled;
    @Value("${tims.kb.gate.threshold:0.75}")
    private double gateThreshold;
    @Value("${tims.kb.gate.soft-band:0.07}")
    private double gateSoftBand;
    @Value("${tims.kb.gate.fallback-tiers:true}")
    private boolean gateFallbackTiers;

    private final KbKnowledgeMapper knowledgeMapper;
    private final EmbeddingService embeddingService;
    private final MilvusVectorStore vectorStore;

    public SearchService(KbKnowledgeMapper knowledgeMapper,
                         EmbeddingService embeddingService,
                         MilvusVectorStore vectorStore) {
        this.knowledgeMapper = knowledgeMapper;
        this.embeddingService = embeddingService;
        this.vectorStore = vectorStore;
    }

    /**
     * 检索入口。
     *
     * @return {query, mode, fallback, total, maxVectorScore, tier, reason, items:[知识全字段 + score + rrfScore + vectorScore]}
     */
    public Map<String, Object> search(Long tenantId, String query, String mode, Integer topK) {
        if (!StringUtils.hasText(query)) {
            throw new BizException(10400, "检索词 query 必填");
        }
        int k = (topK == null || topK <= 0) ? 5 : Math.min(topK, 20);
        String m = !StringUtils.hasText(mode) ? "HYBRID" : mode.trim().toUpperCase();
        if (!List.of("VECTOR", "KEYWORD", "HYBRID").contains(m)) {
            throw new BizException(10400, "mode 仅支持 VECTOR/KEYWORD/HYBRID");
        }

        List<Scored> results;
        boolean fallback = false;
        switch (m) {
            case "KEYWORD" -> results = keywordSearch(tenantId, query, k);
            case "VECTOR" -> {
                List<Scored> vec = tryVectorSearch(tenantId, query, k);
                if (vec == null) {
                    results = keywordSearch(tenantId, query, k);
                    fallback = true;
                } else {
                    results = vec;
                }
            }
            default -> {
                List<Scored> kw = keywordSearch(tenantId, query, CANDIDATE_K);
                List<Scored> vec = tryVectorSearch(tenantId, query, CANDIDATE_K);
                if (vec == null) {
                    // Milvus 不可用 → 降级纯关键词（仍按 topK 截断）
                    fallback = true;
                    results = kw.size() > k ? kw.subList(0, k) : kw;
                } else if (vec.isEmpty()) {
                    // 可用但无向量数据（如尚未同步完成）→ 仅关键词路，不算降级
                    results = kw;
                } else {
                    results = rrfFuse(vec, kw, query, k);
                }
            }
        }

        List<Map<String, Object>> items = new ArrayList<>(results.size());
        double maxVec = -1;
        for (Scored s : results) {
            Map<String, Object> item = new LinkedHashMap<>();
            KbKnowledge k0 = s.knowledge();
            item.put("id", k0.getId());
            item.put("title", k0.getTitle());
            item.put("summary", k0.getSummary());
            item.put("content", k0.getContent());
            item.put("tags", k0.getTags());
            item.put("applyDeviceType", k0.getApplyDeviceType());
            item.put("categoryId", k0.getCategoryId());
            item.put("sourceTicketId", k0.getSourceTicketId());
            item.put("version", k0.getVersion());
            item.put("quoteCount", k0.getQuoteCount());
            item.put("updateTime", k0.getUpdateTime());
            item.put("score", round4(s.score()));
            // 新增：rrfScore 仅 HYBRID 且未降级时有值；vectorScore 仅 VECTOR/HYBRID 有值
            item.put("rrfScore", ("HYBRID".equals(m) && !fallback) ? round4(s.score()) : null);
            item.put("vectorScore", s.vectorScore() == null ? null : round4(s.vectorScore()));
            if (s.vectorScore() != null) {
                maxVec = Math.max(maxVec, s.vectorScore());
            }
            items.add(item);
        }

        Double maxVectorScore = maxVec < 0 ? null : round4(maxVec);
        String tier;
        String reason;
        if (!"VECTOR".equals(m) && !"HYBRID".equals(m)) {
            tier = "A";
            reason = "KEYWORD 模式不做向量门控";
        } else if (!gateEnabled) {
            tier = "A";
            reason = "门控未启用（tims.kb.gate.enabled=false），保持原行为";
        } else if (maxVectorScore == null) {
            if (gateFallbackTiers) {
                tier = "B";
                reason = "无向量相似度（向量检索降级或候选为空），保留原结果，仅供参考";
            } else {
                tier = "C";
                reason = "无向量相似度且 fallback-tiers=false，拒绝返回";
                items.clear();
            }
        } else if (maxVectorScore < gateThreshold) {
            tier = "C";
            reason = String.format("top1 余弦 %.4f < 阈值 %.2f，知识库无可用案例", maxVectorScore, gateThreshold);
            items.clear();
        } else if (maxVectorScore < gateThreshold + gateSoftBand) {
            tier = "B";
            reason = String.format("top1 余弦 %.4f 位于软带 [%.2f, %.2f)，结果仅供参考",
                    maxVectorScore, gateThreshold, gateThreshold + gateSoftBand);
        } else {
            tier = "A";
            reason = String.format("top1 余弦 %.4f ≥ 软带上限 %.2f",
                    maxVectorScore, gateThreshold + gateSoftBand);
        }

        Map<String, Object> resp = new LinkedHashMap<>();
        resp.put("query", query);
        resp.put("mode", m);
        resp.put("fallback", fallback);
        resp.put("gateEnabled", gateEnabled);
        resp.put("gateThreshold", gateThreshold);
        resp.put("maxVectorScore", maxVectorScore);
        resp.put("tier", tier);
        resp.put("reason", reason);
        resp.put("total", items.size());
        resp.put("items", items);
        return resp;
    }

    private static double round4(double v) {
        return Math.round(v * 10000) / 10000.0;
    }

    /** 向量检索；Milvus 不可用/异常返回 null（调用方降级），正常返回可能为空列表 */
    private List<Scored> tryVectorSearch(Long tenantId, String query, int topK) {
        if (!embeddingService.isConfigured() || !vectorStore.isAvailable()) {
            return null;
        }
        try {
            float[] vec = embeddingService.embed(List.of(query)).get(0);
            List<MilvusVectorStore.VecHit> hits = vectorStore.search(vec, topK, tenantId);
            List<Long> ids = hits.stream().map(MilvusVectorStore.VecHit::knowledgeId).toList();
            Map<Long, KbKnowledge> byId = loadPublished(ids);
            List<Scored> out = new ArrayList<>(hits.size());
            for (MilvusVectorStore.VecHit h : hits) {
                KbKnowledge kb = byId.get(h.knowledgeId());
                if (kb != null) { // 刚被驳回/删除的向量尚未撤下时过滤掉
                    out.add(new Scored(kb, h.score(), (double) h.score()));
                }
            }
            return out;
        } catch (Exception e) {
            log.warn("[search] 向量检索失败，降级关键词: {}", e.getMessage());
            return null;
        }
    }

    /** FULLTEXT 关键词检索（ngram，天然适合中文短句） */
    private List<Scored> keywordSearch(Long tenantId, String query, int topK) {
        // ngram token_size=2，单字查询无命中，直接返回空
        if (query.trim().length() < 2) {
            return List.of();
        }
        List<Map<String, Object>> rows = knowledgeMapper.selectFulltextIdScore(tenantId, query.trim(), topK);
        if (rows.isEmpty()) {
            return List.of();
        }
        List<Long> ids = rows.stream().map(r -> ((Number) r.get("id")).longValue()).toList();
        Map<Long, KbKnowledge> byId = loadPublished(ids);
        List<Scored> out = new ArrayList<>(rows.size());
        for (Map<String, Object> r : rows) {
            long id = ((Number) r.get("id")).longValue();
            double score = r.get("ft_score") == null ? 0 : ((Number) r.get("ft_score")).doubleValue();
            KbKnowledge kb = byId.get(id);
            if (kb != null) {
                out.add(new Scored(kb, score, null));
            }
        }
        return out;
    }

    /** RRF 融合 + 设备类型/标签加权；保留每个条目的原始余弦用于门控 */
    private List<Scored> rrfFuse(List<Scored> vec, List<Scored> kw, String query, int topK) {
        Map<Long, Double> rrf = new HashMap<>();
        Map<Long, KbKnowledge> pool = new HashMap<>();
        Map<Long, Double> vecScore = new HashMap<>();
        for (int i = 0; i < vec.size(); i++) {
            rrf.merge(vec.get(i).knowledge().getId(), 1.0 / (RRF_K + i + 1), Double::sum);
            pool.put(vec.get(i).knowledge().getId(), vec.get(i).knowledge());
            vecScore.put(vec.get(i).knowledge().getId(), vec.get(i).vectorScore());
        }
        for (int i = 0; i < kw.size(); i++) {
            rrf.merge(kw.get(i).knowledge().getId(), 1.0 / (RRF_K + i + 1), Double::sum);
            pool.put(kw.get(i).knowledge().getId(), kw.get(i).knowledge());
        }
        List<Scored> fused = new ArrayList<>(rrf.size());
        for (Map.Entry<Long, Double> e : rrf.entrySet()) {
            KbKnowledge kb = pool.get(e.getKey());
            double score = e.getValue();
            String dev = kb.getApplyDeviceType();
            if (StringUtils.hasText(dev) && query.contains(dev)) {
                score *= DEVICE_BOOST;
            }
            if (tagHit(kb.getTags(), query)) {
                score *= TAG_BOOST;
            }
            fused.add(new Scored(kb, score, vecScore.get(e.getKey())));
        }
        fused.sort((a, b) -> Double.compare(b.score(), a.score()));
        return fused.size() > topK ? fused.subList(0, topK) : fused;
    }

    /** tags 为 JSON 数组字符串，任一标签出现在 query 中即命中 */
    private boolean tagHit(String tagsJson, String query) {
        if (!StringUtils.hasText(tagsJson)) {
            return false;
        }
        String t = tagsJson.replace("[", "").replace("]", "").replace("\"", "");
        for (String tag : t.split(",")) {
            String g = tag.trim();
            if (g.length() >= 2 && query.contains(g)) {
                return true;
            }
        }
        return false;
    }

    /** 批量取详情（自动走租户拦截器 + 逻辑删过滤），仅保留 PUBLISHED */
    private Map<Long, KbKnowledge> loadPublished(List<Long> ids) {
        if (ids.isEmpty()) {
            return Map.of();
        }
        return knowledgeMapper.selectBatchIds(ids).stream()
                .filter(x -> "PUBLISHED".equals(x.getStatus()))
                .collect(Collectors.toMap(KbKnowledge::getId, Function.identity(), (a, b) -> a));
    }

    /** 带得分条目：score 为模式内排序分（VECTOR=余弦/HYBRID=RRF/KEYWORD=全文分），vectorScore 为原始余弦 */
    private record Scored(KbKnowledge knowledge, double score, Double vectorScore) {
    }
}
