package com.tims.knowledge.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.knowledge.config.TenantContext;
import com.tims.knowledge.dto.ExtractResult;
import com.tims.knowledge.entity.AiExtracted;
import com.tims.knowledge.entity.KbKnowledge;
import com.tims.knowledge.mapper.AiExtractedMapper;
import com.tims.knowledge.mapper.KbKnowledgeMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.dao.DuplicateKeyException;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.RejectedExecutionException;
import java.util.concurrent.ThreadPoolExecutor;

/**
 * M6 工单关闭 → 知识抽取编排。
 * 1) 幂等：ai_extracted 唯一键 (tenant_id, source_ticket_id)，重复消息直接跳过；
 * 2) 拉工单详情 → 调 ticket-ai 抽取（glm-4-flash 可配）；
 * 3) 抽取失败/服务不可用 → 落 MANUAL_REQUIRED 待人工补录，绝不抛给关单链路；
 * 4) 相似度只生成“建议”（NEW/MERGE/SKIP），不自动合并、不自动覆盖，等待审核人确认。
 */
@Service
public class ExtractionService {

    private static final Logger log = LoggerFactory.getLogger(ExtractionService.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final AiExtractedMapper extractedMapper;
    private final KbKnowledgeMapper knowledgeMapper;
    private final ExtractAiClient aiClient;
    private final OrderClient orderClient;
    private final EmbeddingService embeddingService;
    private final MilvusVectorStore vectorStore;
    /** 抽取异步执行器（与 MQ 消费线程解耦）与积压指标 */
    private final ThreadPoolExecutor extractExecutor;
    private final ExtractQueueMetrics queueMetrics;

    @Value("${tims.kb.extract.dedup-threshold:0.92}")
    private double dedupThreshold;

    @Value("${tims.kb.extract.dedup-skip-threshold:0.98}")
    private double dedupSkipThreshold;

    @Value("${tims.kb.extract.top-k:5}")
    private int topK;

    @Value("${tims.kb.extract.model:glm-4-flash}")
    private String extractModel;

    /** 抽取失败后是否即时重试 1 次（不做退避自动重试） */
    @Value("${tims.kb.extract.executor.retry-once:true}")
    private boolean retryOnce;

    public ExtractionService(AiExtractedMapper extractedMapper,
                             KbKnowledgeMapper knowledgeMapper,
                             ExtractAiClient aiClient,
                             OrderClient orderClient,
                             EmbeddingService embeddingService,
                             MilvusVectorStore vectorStore,
                             @org.springframework.beans.factory.annotation.Qualifier("extractExecutor")
                             ThreadPoolExecutor extractExecutor,
                             ExtractQueueMetrics queueMetrics) {
        this.extractedMapper = extractedMapper;
        this.knowledgeMapper = knowledgeMapper;
        this.aiClient = aiClient;
        this.orderClient = orderClient;
        this.embeddingService = embeddingService;
        this.vectorStore = vectorStore;
        this.extractExecutor = extractExecutor;
        this.queueMetrics = queueMetrics;
    }

    /**
     * 消费入口：只做幂等占位（ai_extracted → PROCESSING）+ 投递内部执行器，随即返回。
     * 真正 9~10s 的抽取在独立线程池执行，集中关单时不再占住 MQ 消费线程造成排队雪崩。
     */
    public void handleClosedEvent(Map<String, Object> event, Long tenantId) {
        Long ticketId = toLong(event == null ? null : event.get("ticketId"));
        if (ticketId == null) {
            log.warn("[m6] 事件缺少 ticketId，忽略: {}", event);
            return;
        }
        String ticketNo = str(event.get("ticketNo"));
        String deviceType = str(event.get("deviceType"));

        AiExtracted row = new AiExtracted();
        row.setTenantId(tenantId);
        row.setSourceTicketId(ticketId);
        row.setSourceTicketNo(ticketNo);
        row.setSourceDeviceType(deviceType);
        row.setModel(extractModel);
        row.setDedupAction("NEW");
        row.setStatus("PROCESSING");
        row.setCreateTime(LocalDateTime.now());

        TenantContext.setOverride(tenantId);
        try {
            if (alreadyExtracted(tenantId, ticketId)) {
                log.info("[m6] 工单 {} 已抽取过，重复消息跳过", ticketNo);
                return;
            }
            try {
                extractedMapper.insert(row);
            } catch (DuplicateKeyException e) {
                log.info("[m6] 工单 {} 并发重复消息，唯一键拦截，忽略", ticketId);
                return;
            }
        } finally {
            TenantContext.clearOverride();
        }

        long enqueueAt = System.currentTimeMillis();
        try {
            extractExecutor.execute(() -> {
                queueMetrics.recordStart(System.currentTimeMillis() - enqueueAt);
                processRow(row, tenantId, ticketId, ticketNo, deviceType);
            });
            queueMetrics.recordSubmit();
            log.info("[m6] 工单 {} 已入抽取队列 queue={} active={}", ticketNo,
                    extractExecutor.getQueue().size(), extractExecutor.getActiveCount());
        } catch (RejectedExecutionException e) {
            queueMetrics.recordReject();
            log.warn("[m6] 工单 {} 抽取队列已满，转人工补录", ticketNo);
            row.setStatus("MANUAL_REQUIRED");
            row.setSourceTitle(ticketNo);
            row.setTitle(ticketNo);
            row.setTags("[]");
            row.setErrorMsg("抽取队列已满，未执行 AI 抽取，请人工补录");
            row.setDedupNote("队列拒绝，未做相似度判定；请人工补录后提交审核");
            try {
                extractedMapper.updateById(row);
            } catch (Exception ignore) {
                log.warn("[m6] 队列拒绝后落库失败 ticket={}", ticketId);
            }
        }
    }

    /** 执行器任务：工单详情 → AI 抽取（失败即时重试 1 次）→ 落库；异常一律转人工补录，不向上抛出 */
    private void processRow(AiExtracted row, Long tenantId, Long ticketId, String ticketNo, String deviceType) {
        TenantContext.setOverride(tenantId);
        try {
            OrderClient.Detail detail = null;
            String errMsg = null;
            try {
                detail = orderClient.detail(tenantId, ticketId);
            } catch (Exception e) {
                errMsg = "工单详情获取失败: " + e.getMessage();
                log.warn("[m6] 工单 {} 详情获取失败: {}", ticketNo, e.getMessage());
            }

            Map<String, Object> payload = detail == null ? null
                    : buildPayload(tenantId, ticketId, ticketNo, deviceType, detail);
            ExtractResult result = null;
            if (payload != null) {
                try {
                    result = aiClient.extract(tenantId, payload);
                } catch (Exception e) {
                    errMsg = "AI 抽取失败: " + e.getMessage();
                    log.warn("[m6] 工单 {} 抽取失败: {}，即时重试 1 次", ticketNo, e.getMessage());
                    if (retryOnce) {
                        queueMetrics.recordRetry();
                        try {
                            result = aiClient.extract(tenantId, payload);
                            errMsg = null;
                        } catch (Exception e2) {
                            errMsg = "AI 抽取失败(已重试 1 次): " + e2.getMessage();
                            log.warn("[m6] 工单 {} 重试仍失败: {}", ticketNo, e2.getMessage());
                        }
                    }
                }
            }

            row.setSourceTicketNo(detail != null && !detail.ticketNo.isEmpty() ? detail.ticketNo : ticketNo);
            row.setSourceDeviceType(detail != null && !detail.deviceType.isEmpty() ? detail.deviceType : deviceType);
            row.setModel(result != null ? result.getModel() : extractModel);

            if (result == null) {
                row.setSourceTitle(detail != null ? detail.title : ticketNo);
                row.setTitle(detail != null && !detail.title.isEmpty() ? detail.title : ticketNo);
                row.setFaultPhenomenon(detail == null ? "" : detail.description);
                row.setSolutionSteps(detail == null ? "" : detail.resolveNote);
                row.setTags("[]");
                row.setStatus("MANUAL_REQUIRED");
                row.setErrorMsg(truncate(errMsg == null ? "抽取失败，请人工补录" : errMsg, 250));
                row.setDedupNote("AI 抽取不可用，未做相似度判定；请人工补录后提交审核");
            } else {
                row.setSourceTitle(detail != null ? detail.title : ticketNo);
                row.setTitle(result.getTitle());
                row.setDeviceType(result.getDeviceType());
                row.setFaultPhenomenon(result.getFaultPhenomenon());
                row.setTroubleshootSteps(result.getTroubleshootSteps());
                row.setSolutionSteps(result.getSolutionSteps());
                row.setKeyPoints(result.getKeyPoints());
                row.setTags(tagsJson(result.getTags()));
                row.setStatus("PENDING_REVIEW");
                applyDedupSuggestion(row, result, tenantId);
            }

            if (result == null) {
                queueMetrics.recordFailure();
            } else {
                queueMetrics.recordSuccess();
            }
            extractedMapper.updateById(row);
            if (result != null) {
                orderClient.markAiExtracted(tenantId, ticketId);
            }
            log.info("[m6] 工单 {} 抽取完成 status={} dedup={} target={}",
                    row.getSourceTicketNo(), row.getStatus(), row.getDedupAction(), row.getDedupTargetId());
        } catch (Exception e) {
            queueMetrics.recordFailure();
            log.error("[m6] 工单 {} 异步抽取异常: {}", ticketNo, e.getMessage(), e);
            row.setStatus("MANUAL_REQUIRED");
            row.setErrorMsg(truncate("抽取异常: " + e.getMessage(), 250));
            row.setDedupNote("异步执行异常，请人工补录");
            try {
                extractedMapper.updateById(row);
            } catch (Exception ignore) {
                log.warn("[m6] 异常兜底落库失败 ticket={}", ticketId);
            }
        } finally {
            TenantContext.clearOverride();
        }
    }

    private boolean alreadyExtracted(Long tenantId, Long ticketId) {
        return extractedMapper.selectCount(new LambdaQueryWrapper<AiExtracted>()
                .eq(AiExtracted::getTenantId, tenantId)
                .eq(AiExtracted::getSourceTicketId, ticketId)) > 0;
    }

    private Map<String, Object> buildPayload(Long tenantId, Long ticketId, String ticketNo,
                                             String eventDeviceType, OrderClient.Detail detail) {
        Map<String, Object> p = new LinkedHashMap<>();
        p.put("tenantId", tenantId);
        p.put("ticketId", ticketId);
        p.put("ticketNo", detail.ticketNo.isEmpty() ? ticketNo : detail.ticketNo);
        p.put("title", detail.title);
        p.put("deviceType", detail.deviceType.isEmpty() ? eventDeviceType : detail.deviceType);
        p.put("description", detail.description);
        p.put("resolveNote", detail.resolveNote);
        p.put("comments", detail.comments);
        p.put("flows", detail.flows);
        return p;
    }

    /**
     * 只计算相似度并给出建议，不执行任何合并/覆盖动作。
     * ≥0.98 建议跳过；≥0.92 建议合并；其余建议新建。最终由审核人在审核中心确认。
     */
    private void applyDedupSuggestion(AiExtracted row, ExtractResult result, Long tenantId) {
        row.setDedupAction("NEW");
        if (!embeddingService.isConfigured() || !vectorStore.isAvailable()) {
            row.setDedupNote("向量库不可用，未计算相似度；请人工判断应新建、合并或跳过");
            return;
        }
        try {
            String text = joinText(result.getTitle(), result.getFaultPhenomenon(),
                    result.getSolutionSteps(), String.join(" ", result.getTags() == null ? List.of() : result.getTags()));
            float[] vec = embeddingService.embed(List.of(text)).get(0);
            List<MilvusVectorStore.VecHit> hits = vectorStore.search(vec, topK, tenantId);
            if (hits == null || hits.isEmpty()) {
                row.setDedupNote("相似度计算完成：未找到相似条目，建议新建");
                return;
            }
            MilvusVectorStore.VecHit top = hits.get(0);
            for (MilvusVectorStore.VecHit h : hits) {
                if (h.score() > top.score()) {
                    top = h;
                }
            }
            KbKnowledge target = knowledgeMapper.selectById(top.knowledgeId());
            if (target == null) {
                row.setDedupNote("相似度计算完成：命中条目已删除，建议新建");
                return;
            }
            double score = top.score();
            String action;
            if (score >= dedupSkipThreshold) {
                action = "SKIP";
            } else if (score >= dedupThreshold) {
                action = "MERGE";
            } else {
                action = "NEW";
            }
            row.setDedupAction(action);
            row.setDedupTargetId(target.getId());
            row.setDedupTargetTitle(target.getTitle());
            row.setDedupScore(BigDecimal.valueOf(score).setScale(4, RoundingMode.HALF_UP));
            row.setDedupNote(buildDiffNote(score, action, target, result));
        } catch (Exception e) {
            log.warn("[m6] 相似度计算失败: {}", e.getMessage());
            row.setDedupAction("NEW");
            row.setDedupNote("相似度计算失败，请人工判断应新建、合并或跳过");
        }
    }

    /** 生成“相似度 + 关键差异”摘要，供审核人判断（非自动决策依据） */
    private String buildDiffNote(double score, String action, KbKnowledge target, ExtractResult result) {
        StringBuilder sb = new StringBuilder();
        sb.append("向量余弦相似度 ").append(String.format("%.4f", score)).append("；");
        sb.append("最相似条目 #").append(target.getId()).append("《").append(target.getTitle()).append("》；");
        Set<String> oldTags = parseTags(target.getTags());
        Set<String> newTags = new HashSet<>(result.getTags() == null ? List.of() : result.getTags());
        List<String> added = new ArrayList<>(newTags);
        added.removeAll(oldTags);
        List<String> kept = new ArrayList<>(oldTags);
        kept.removeAll(newTags);
        if (!added.isEmpty()) {
            sb.append("新条目新增标签：").append(String.join("、", added)).append("；");
        }
        if (!kept.isEmpty()) {
            sb.append("已有条目独有标签：").append(String.join("、", kept)).append("；");
        }
        int newLen = length(result.getSolutionSteps());
        int oldLen = length(target.getContent());
        sb.append("新条目解决步骤约 ").append(newLen).append(" 字，已有条目正文约 ").append(oldLen).append(" 字；");
        if ("MERGE".equals(action)) {
            sb.append("建议合并到该条目（须人工确认）");
        } else if ("SKIP".equals(action)) {
            sb.append("高度疑似重复，建议跳过（须人工确认）");
        } else {
            sb.append("相似度低于阈值，建议新建");
        }
        return sb.toString();
    }

    private Set<String> parseTags(String json) {
        Set<String> set = new HashSet<>();
        if (json == null || json.isBlank()) {
            return set;
        }
        try {
            JsonNode n = MAPPER.readTree(json);
            if (n.isArray()) {
                n.forEach(x -> {
                    if (!x.asText("").isBlank()) {
                        set.add(x.asText());
                    }
                });
            }
        } catch (Exception ignored) {
            // 非法 JSON 视为无标签
        }
        return set;
    }

    private String tagsJson(List<String> tags) {
        try {
            return MAPPER.writeValueAsString(tags == null ? List.of() : tags);
        } catch (Exception e) {
            return "[]";
        }
    }

    private static String joinText(String... parts) {
        StringBuilder sb = new StringBuilder();
        for (String p : parts) {
            if (p != null && !p.isBlank()) {
                sb.append(p).append('\n');
            }
        }
        return sb.toString();
    }

    private static int length(String s) {
        return s == null ? 0 : s.length();
    }

    private static String str(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static Long toLong(Object o) {
        if (o instanceof Number n) {
            return n.longValue();
        }
        if (o != null && String.valueOf(o).matches("\\d+")) {
            return Long.parseLong(String.valueOf(o));
        }
        return null;
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }
}
