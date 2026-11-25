package com.tims.ai.fallback;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.ai.config.AiProperties;
import com.tims.common.exception.BizException;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.text.Normalizer;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * C 档兜底建议：生成后的落库与工单关闭后的实际处置回填。
 * 只做记录，不写 kb_knowledge、不动 Milvus、不触发审核入库。
 */
@Service
public class FallbackSuggestionService {

    private static final Logger log = LoggerFactory.getLogger(FallbackSuggestionService.class);

    /** 前端与日志统一使用的“无库内依据”标记 */
    public static final String MARKER = "【无知识库依据，仅供参考】";

    /** 记录在配对表里的 prompt 版本后缀 */
    public static final String PROMPT_VERSION_SUFFIX = "+fallback-v1";

    /** 字符二元组 Dice 判定为“一致”的阈值；先用 0.30 起步，后续按真实回填数据校准 */
    static final double CONSISTENT_THRESHOLD = 0.30;

    /** 少于该字符数不做判定，避免“已处理”之类短句误判 */
    static final int MIN_COMPARE_CHARS = 8;

    private final FallbackPairMapper mapper;
    private final AiProperties props;
    private final ObjectMapper json;
    private final FallbackIntakeClient intakeClient;

    public FallbackSuggestionService(FallbackPairMapper mapper, AiProperties props, ObjectMapper json,
                                     FallbackIntakeClient intakeClient) {
        this.mapper = mapper;
        this.props = props;
        this.json = json;
        this.intakeClient = intakeClient;
    }

    /** 开关默认 false；关闭时调用方不应产生任何额外行为 */
    public boolean isEnabled() {
        return props.getFallback() != null && props.getFallback().isEnabled();
    }

    /**
     * 记录一条 C 档建议。失败只告警，不影响本次问答返回。
     *
     * @return 新记录 id；落库失败返回 null
     */
    public Long record(Long tenantId, Long ticketId, String ticketNo, String suggestion, String promptVersion) {
        return record(tenantId, ticketId, ticketNo, suggestion, promptVersion, null, null);
    }

    /**
     * 记录一条 C 档建议。失败只告警，不影响本次问答返回。
     *
     * @param sessionId 可选问答会话ID，仅用于后续回填入库的来源回溯
     * @return 新记录 id；落库失败返回 null
     */
    public Long record(Long tenantId, Long ticketId, String ticketNo, String suggestion, String promptVersion,
                       String sessionId) {
        return record(tenantId, ticketId, ticketNo, suggestion, promptVersion, sessionId, null);
    }

    /**
     * 记录一条 C 档建议。失败只告警，不影响本次问答返回。
     *
     * @param sessionId   可选问答会话ID，仅用于后续回填入库的来源回溯
     * @param ticketTitle 可选工单标题快照，回填入库时用于生成待审标题（可空）
     * @return 新记录 id；落库失败返回 null
     */
    public Long record(Long tenantId, Long ticketId, String ticketNo, String suggestion, String promptVersion,
                       String sessionId, String ticketTitle) {
        if (suggestion == null || suggestion.isBlank()) {
            return null;
        }
        try {
            FallbackPair p = new FallbackPair();
            p.setTenantId(tenantId);
            p.setTicketId(ticketId);
            p.setTicketNo(ticketNo);
            p.setTicketTitle(ticketTitle == null || ticketTitle.isBlank() ? null : ticketTitle.trim());
            p.setTier("C");
            p.setSuggestionText(suggestion.trim());
            p.setModel(props.getModel());
            p.setPromptVersion(promptVersion == null ? "fallback-v1" : promptVersion + PROMPT_VERSION_SUFFIX);
            p.setSessionId(sessionId);
            p.setNoKbBasis(1);
            p.setSuggestTime(LocalDateTime.now());
            p.setIsTest(0);
            p.setDataSource("real");
            mapper.insert(p);
            return p.getId();
        } catch (Exception e) {
            log.warn("C 档兜底建议落库失败，忽略：{}", e.getMessage());
            return null;
        }
    }

    /**
     * 回填实际处置，并自动比对一致性。
     * 旧口径（字符二元组 Dice）与新口径（处置侧覆盖率）同时写入，两列并存便于对照。
     * 文本太短（&lt; {@value #MIN_COMPARE_CHARS} 字符）时旧口径记 NULL（无法判定）。
     */
    public Map<String, Object> backfill(Long tenantId, Long id, String disposition, Long userId) {
        FallbackPair p = id == null ? null : mapper.selectById(id);
        if (p == null || !Objects.equals(p.getTenantId(), tenantId)) {
            throw new BizException(10404, "兜底建议记录不存在");
        }
        if (disposition == null || disposition.isBlank()) {
            throw new BizException(10400, "实际处置不能为空");
        }
        double score = dice(p.getSuggestionText(), disposition);
        Integer consistent = score < 0 ? null : (score >= CONSISTENT_THRESHOLD ? 1 : 0);

        p.setActualDisposition(disposition.trim());
        p.setDispositionBy(userId);
        p.setDispositionTime(LocalDateTime.now());
        p.setConsistent(consistent);
        p.setConsistencyScore(score < 0 ? null : BigDecimal.valueOf(score).setScale(4, RoundingMode.HALF_UP));
        CoverageScorer.Result cov = CoverageScorer.score(p.getSuggestionText(), disposition);
        applyCoverage(p, cov);
        mapper.updateById(p);
        try {
            maybeIntake(p);
        } catch (Exception e) {
            log.warn("[fallback-intake] pair={} 投递异常，忽略：{}", p.getId(), e.getMessage());
        }

        Map<String, Object> out = new HashMap<>();
        // 雪花 ID 超出 JS 安全整数范围，按字符串返回
        out.put("id", String.valueOf(p.getId()));
        out.put("consistent", consistent);
        out.put("consistencyScore", p.getConsistencyScore());
        out.put("coverageScore", p.getCoverageScore());
        out.put("coverageHits", p.getCoverageHits());
        out.put("coverageSegments", p.getCoverageSegments());
        out.put("coverageVerdict", p.getCoverageVerdict());
        out.put("coverageDetail", cov == null ? null : CoverageScorer.toPlain(cov.detail()));
        return out;
    }

    /**
     * 建议→回填→入库：回填后按灰度决定是否投递待审条目。
     * 只投递，不写知识库；enabled=false、非真实样本、非 CONSISTENT、置信分不足、抽样未命中任一不满足即跳过。
     */
    private void maybeIntake(FallbackPair p) {
        AiProperties.Fallback.Intake cfg = props.getFallback() == null ? null : props.getFallback().getIntake();
        if (cfg == null || !cfg.isEnabled()) {
            return;
        }
        if (p.getIsTest() != null && p.getIsTest() != 0) {
            return;
        }
        if ("synthetic".equalsIgnoreCase(p.getDataSource())) {
            return;
        }
        String verdict = p.getCoverageVerdict();
        boolean consistent = "CONSISTENT".equals(verdict)
                || (verdict == null && Integer.valueOf(1).equals(p.getConsistent()));
        if (!consistent) {
            return;
        }
        BigDecimal conf = p.getCoverageScore() != null ? p.getCoverageScore() : p.getConsistencyScore();
        if (conf == null || conf.doubleValue() < cfg.getMinConfidence()) {
            return;
        }
        double ratio = cfg.getGrayRatio();
        if (ratio <= 0) {
            return;
        }
        long bucket = Math.floorMod(p.getId() == null ? 0L : p.getId(), 100L);
        if (bucket >= Math.round(ratio * 100)) {
            return;
        }
        intakeClient.submit(p, conf.setScale(4, RoundingMode.HALF_UP).toPlainString());
    }

    /**
     * 按新口径重算存量记录：只处理“有处置文本”的行，测试行默认排除。
     *
     * @param includeTest true 表示连同 is_test=1 的行一起算
     */
    public Map<String, Object> recompute(boolean includeTest) {
        LambdaQueryWrapper<FallbackPair> w = new LambdaQueryWrapper<>();
        if (!includeTest) {
            w.and(q -> q.eq(FallbackPair::getIsTest, 0).or().isNull(FallbackPair::getIsTest));
        }
        List<FallbackPair> rows = mapper.selectList(w);
        int total = rows.size();
        int updated = 0;
        int skipped = 0;
        List<Map<String, Object>> samples = new ArrayList<>();
        for (FallbackPair p : rows) {
            String disposition = p.getActualDisposition();
            if (disposition == null || disposition.isBlank()) {
                skipped++;
                continue;
            }
            CoverageScorer.Result cov = CoverageScorer.score(p.getSuggestionText(), disposition);
            if (cov == null) {
                skipped++;
                continue;
            }
            applyCoverage(p, cov);
            try {
                mapper.updateById(p);
                updated++;
            } catch (Exception e) {
                log.warn("重算失败 id={}：{}", p.getId(), e.getMessage());
                continue;
            }
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", String.valueOf(p.getId()));
            m.put("ticketNo", p.getTicketNo());
            m.put("isTest", p.getIsTest());
            m.put("dispositionChars", CoverageScorer.normalize(disposition).length());
            m.put("consistencyScore", p.getConsistencyScore());
            m.put("coverageScore", p.getCoverageScore());
            m.put("coverageHits", p.getCoverageHits());
            m.put("coverageSegments", p.getCoverageSegments());
            m.put("coverageVerdict", p.getCoverageVerdict());
            m.put("coverageDetail", CoverageScorer.toPlain(cov.detail()));
            m.put("dataSource", p.getDataSource());
            m.put("syntheticClass", p.getSyntheticClass());
            m.put("classNote", p.getClassNote());
            samples.add(m);
        }
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("includeTest", includeTest);
        out.put("total", total);
        out.put("updated", updated);
        out.put("skipped", skipped);
        out.put("samples", samples);
        return out;
    }

    /**
     * 列出配对记录（附带新口径逐段明细），默认排除测试数据。
     * 明细用于人工核对“哪些片段命中、命中了建议里的哪句话”。
     */
    public List<Map<String, Object>> list(boolean includeTest) {
        LambdaQueryWrapper<FallbackPair> w = new LambdaQueryWrapper<>();
        if (!includeTest) {
            w.and(q -> q.eq(FallbackPair::getIsTest, 0).or().isNull(FallbackPair::getIsTest));
        }
        w.orderByAsc(FallbackPair::getSuggestTime);
        List<Map<String, Object>> out = new ArrayList<>();
        for (FallbackPair p : mapper.selectList(w)) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", String.valueOf(p.getId()));
            m.put("ticketNo", p.getTicketNo());
            m.put("tier", p.getTier());
            m.put("isTest", p.getIsTest());
            m.put("suggestTime", p.getSuggestTime());
            m.put("dispositionTime", p.getDispositionTime());
            m.put("dispositionChars", p.getActualDisposition() == null ? 0
                    : CoverageScorer.normalize(p.getActualDisposition()).length());
            m.put("actualDisposition", p.getActualDisposition());
            m.put("consistent", p.getConsistent());
            m.put("consistencyScore", p.getConsistencyScore());
            m.put("coverageScore", p.getCoverageScore());
            m.put("coverageHits", p.getCoverageHits());
            m.put("coverageSegments", p.getCoverageSegments());
            m.put("coverageVerdict", p.getCoverageVerdict());
            m.put("coverageDetail", parseDetail(p.getCoverageDetail()));
            m.put("dataSource", p.getDataSource());
            m.put("syntheticClass", p.getSyntheticClass());
            m.put("classNote", p.getClassNote());
            out.add(m);
        }
        return out;
    }

    /** 写入新口径的四个字段；无法判定（无处置/过短）时置空 */
    private void applyCoverage(FallbackPair p, CoverageScorer.Result cov) {
        if (cov == null) {
            p.setCoverageScore(null);
            p.setCoverageHits(null);
            p.setCoverageSegments(null);
            p.setCoverageDetail(null);
            p.setCoverageVerdict(null);
            return;
        }
        p.setCoverageScore(BigDecimal.valueOf(cov.score()).setScale(4, RoundingMode.HALF_UP));
        p.setCoverageHits(cov.hits());
        p.setCoverageSegments(cov.segments());
        p.setCoverageVerdict(verdict(cov.score(), cov.segments()));
        try {
            p.setCoverageDetail(json.writeValueAsString(CoverageScorer.toPlain(cov.detail())));
        } catch (Exception e) {
            p.setCoverageDetail(null);
        }
    }

    /**
     * 新口径判定：有效片段不足 minSegments 记 INSUFFICIENT（样本不足，不参与阈值比较）；
     * 否则覆盖率 ≥ consistentThreshold 记 CONSISTENT，其余记 INCONSISTENT。
     * 两个参数都来自配置 tims.ai.fallback.*，不写死在代码里。
     */
    private String verdict(double score, int segments) {
        AiProperties.Fallback cfg = props.getFallback();
        int minSegments = cfg == null ? 3 : cfg.getMinSegments();
        double threshold = cfg == null ? 0.60 : cfg.getConsistentThreshold();
        if (segments < minSegments) {
            return "INSUFFICIENT";
        }
        return score >= threshold ? "CONSISTENT" : "INCONSISTENT";
    }

    private Object parseDetail(String raw) {
        if (raw == null || raw.isBlank()) {
            return null;
        }
        try {
            return json.readValue(raw, List.class);
        } catch (Exception e) {
            return raw;
        }
    }

    /**
     * 字符二元组 Dice（NFKC 归一化、小写、仅保留字母/数字/汉字）。
     *
     * @return 0-1；任一文本过短返回 -1（无法判定）
     */
    static double dice(String a, String b) {
        String na = normalize(a);
        String nb = normalize(b);
        if (na.length() < MIN_COMPARE_CHARS || nb.length() < MIN_COMPARE_CHARS) {
            return -1;
        }
        Map<String, Integer> bigrams = new HashMap<>();
        for (int i = 0; i < na.length() - 1; i++) {
            bigrams.merge(na.substring(i, i + 2), 1, Integer::sum);
        }
        int hit = 0;
        int totalB = 0;
        for (int i = 0; i < nb.length() - 1; i++) {
            String g = nb.substring(i, i + 2);
            totalB++;
            Integer c = bigrams.get(g);
            if (c != null && c > 0) {
                hit++;
                bigrams.put(g, c - 1);
            }
        }
        int totalA = na.length() - 1;
        if (totalA + totalB == 0) {
            return -1;
        }
        return 2.0 * hit / (totalA + totalB);
    }

    private static String normalize(String s) {
        if (s == null) {
            return "";
        }
        String n = Normalizer.normalize(s, Normalizer.Form.NFKC).toLowerCase();
        StringBuilder sb = new StringBuilder(n.length());
        for (int i = 0; i < n.length(); i++) {
            char c = n.charAt(i);
            if (Character.isLetterOrDigit(c)) {
                sb.append(c);
            }
        }
        return sb.toString();
    }
}
