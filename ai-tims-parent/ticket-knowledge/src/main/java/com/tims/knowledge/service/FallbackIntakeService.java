package com.tims.knowledge.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.common.exception.BizException;
import com.tims.knowledge.dto.ExtractResult;
import com.tims.knowledge.dto.FallbackIntakeRequest;
import com.tims.knowledge.entity.AiExtracted;
import com.tims.knowledge.mapper.AiExtractedMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

/**
 * 建议→回填：把 C 档建议与处置的配对记录转成 ai_extracted 待审条目。
 * 硬边界：只写 ai_extracted（status=PENDING_REVIEW），不写 kb_knowledge、不写 Milvus；
 * 去重/关系判别复用 {@link ExtractionService#applyDedupSuggestion}，与工单抽取同一口径。
 */
@Service
public class FallbackIntakeService {

    private static final Logger log = LoggerFactory.getLogger(FallbackIntakeService.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();
    /** 配对ID异常时的占位序列，初值取纳秒时间，避免与历史值重复。 */
    private static final AtomicLong FALLBACK_TICKET_SEQ = new AtomicLong(System.nanoTime());

    public static final String SOURCE_FALLBACK = "FALLBACK";
    public static final String STATUS_PENDING = "PENDING_REVIEW";

    private final AiExtractedMapper extractedMapper;
    private final ExtractionService extractionService;

    @Value("${tims.kb.fallback-intake.min-confidence:0.60}")
    private double minConfidence;

    @Value("${tims.kb.fallback-intake.max-per-day:20}")
    private int maxPerDay;

    public FallbackIntakeService(AiExtractedMapper extractedMapper, ExtractionService extractionService) {
        this.extractedMapper = extractedMapper;
        this.extractionService = extractionService;
    }

    /**
     * 接收一条回填待审条目。
     * 返回 accepted=false 时：DUPLICATE（幂等命中，id 为既有条目）/ LOW_CONFIDENCE / DAILY_CAP。
     */
    public Map<String, Object> intake(FallbackIntakeRequest req) {
        if (req == null || req.getTenantId() == null || req.getFallbackPairId() == null) {
            throw new BizException(10400, "来源租户与配对记录ID不能为空");
        }
        if (isBlank(req.getActualDisposition())) {
            throw new BizException(10400, "实际处置不能为空");
        }
        BigDecimal conf = req.getConfidence();
        if (conf == null) {
            return rejected("NO_CONFIDENCE");
        }
        if (conf.doubleValue() < minConfidence) {
            return rejected("LOW_CONFIDENCE");
        }

        Long existing = findExisting(req.getTenantId(), req.getFallbackPairId());
        if (existing != null) {
            Map<String, Object> out = new LinkedHashMap<>();
            out.put("accepted", false);
            out.put("reason", "DUPLICATE");
            out.put("id", String.valueOf(existing));
            return out;
        }

        Long todayCount = extractedMapper.selectCount(new LambdaQueryWrapper<AiExtracted>()
                .eq(AiExtracted::getTenantId, req.getTenantId())
                .eq(AiExtracted::getSourceType, SOURCE_FALLBACK)
                .ge(AiExtracted::getCreateTime, LocalDate.now().atStartOfDay()));
        if (todayCount != null && todayCount >= maxPerDay) {
            return rejected("DAILY_CAP");
        }

        AiExtracted row = buildRow(req, conf);
        ExtractResult result = buildExtractResult(row);
        extractionService.applyDedupSuggestion(row, result, req.getTenantId());
        extractedMapper.insert(row);
        log.info("[fallback-intake] accepted pair={} extractedId={} dedup={} conf={}",
                req.getFallbackPairId(), row.getId(), row.getDedupAction(), conf);

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("accepted", true);
        out.put("id", String.valueOf(row.getId()));
        out.put("status", row.getStatus());
        out.put("dedupAction", row.getDedupAction());
        return out;
    }

    private Long findExisting(Long tenantId, Long pairId) {
        List<AiExtracted> list = extractedMapper.selectList(new LambdaQueryWrapper<AiExtracted>()
                .eq(AiExtracted::getTenantId, tenantId)
                .eq(AiExtracted::getSourceType, SOURCE_FALLBACK)
                .eq(AiExtracted::getSourceRefId, pairId)
                .orderByDesc(AiExtracted::getId)
                .last("limit 1"));
        return list == null || list.isEmpty() ? null : list.get(0).getId();
    }

    /**
     * 生成无工单回填的占位来源工单ID。
     * 正常情况用 -fallbackPairId；配对ID异常（为空或非正）时退到 BIGINT 负区间极值 + 自增序列，
     * 保证结果非零、且不会与 -pairId 或真实雪花ID重叠。
     */
    private static long fallbackTicketId(Long fallbackPairId) {
        if (fallbackPairId != null && fallbackPairId > 0L) {
            return -fallbackPairId;
        }
        long seq = FALLBACK_TICKET_SEQ.incrementAndGet();
        return Long.MIN_VALUE + seq;
    }

    private AiExtracted buildRow(FallbackIntakeRequest req, BigDecimal conf) {
        AiExtracted row = new AiExtracted();
        row.setTenantId(req.getTenantId());
        // 无工单回填也要满足 source_ticket_id NOT NULL + uk_tenant_ticket(tenant_id, source_ticket_id)：
        // 用负值占位，既不与真实雪花ID（正数）冲突，又保证每个配对唯一；来源仍由 source_ref_id 回溯。
        row.setSourceTicketId(fallbackTicketId(req.getFallbackPairId()));
        row.setSourceTicketNo(isBlank(req.getTicketNo()) ? "FALLBACK#" + req.getFallbackPairId() : req.getTicketNo().trim());
        row.setSourceTitle("C 档建议回填");
        row.setSourceType(SOURCE_FALLBACK);
        row.setSourceRefId(req.getFallbackPairId());
        row.setSourceSessionId(blankToNull(req.getSessionId()));
        row.setSourceConfidence(conf);

        row.setTitle(buildTitle(req));
        row.setFaultPhenomenon(null);
        row.setSolutionSteps(req.getActualDisposition().trim());
        row.setTags(tagsJson());
        StringBuilder key = new StringBuilder();
        key.append("来源：C 档建议回填（ai_fallback_pair#").append(req.getFallbackPairId()).append("）；");
        key.append("模型：").append(isBlank(req.getModel()) ? "-" : req.getModel()).append("；");
        key.append("置信分：").append(conf.stripTrailingZeros().toPlainString());
        if (!isBlank(req.getSuggestionText())) {
            key.append("\n模型建议原文：\n").append(req.getSuggestionText().trim());
        }
        row.setKeyPoints(key.toString());
        row.setModel(req.getModel());
        row.setStatus(STATUS_PENDING);
        row.setCreateTime(LocalDateTime.now());
        row.setUpdateTime(LocalDateTime.now());
        return row;
    }

    private ExtractResult buildExtractResult(AiExtracted row) {
        ExtractResult r = new ExtractResult();
        r.setTitle(row.getTitle());
        r.setFaultPhenomenon(row.getFaultPhenomenon());
        r.setSolutionSteps(row.getSolutionSteps());
        r.setTags(List.of("建议回填"));
        r.setModel(row.getModel());
        return r;
    }

    private static String buildTitle(FallbackIntakeRequest req) {
        String text = req.getActualDisposition().trim();
        int cut = text.indexOf('\n');
        String first = cut > 0 ? text.substring(0, cut) : text;
        first = first.replaceAll("\\s+", " ").trim();
        if (first.length() > 120) {
            first = first.substring(0, 120);
        }
        return first.isBlank() ? "建议回填-" + req.getFallbackPairId() : first;
    }

    private static String tagsJson() {
        try {
            return MAPPER.writeValueAsString(List.of("建议回填"));
        } catch (Exception e) {
            return "[\"建议回填\"]";
        }
    }

    private static Map<String, Object> rejected(String reason) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("accepted", false);
        out.put("reason", reason);
        return out;
    }

    private static boolean isBlank(String s) {
        return s == null || s.isBlank();
    }

    private static String blankToNull(String s) {
        return s == null || s.isBlank() ? null : s.trim();
    }
}
