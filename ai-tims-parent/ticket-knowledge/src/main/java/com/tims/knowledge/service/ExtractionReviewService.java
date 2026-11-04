package com.tims.knowledge.service;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.common.exception.BizException;
import com.tims.knowledge.entity.AiExtracted;
import com.tims.knowledge.entity.KbKnowledge;
import com.tims.knowledge.entity.KbKnowledgeHistory;
import com.tims.knowledge.mapper.AiExtractedMapper;
import com.tims.knowledge.mapper.KbKnowledgeHistoryMapper;
import com.tims.knowledge.mapper.KbKnowledgeMapper;
import com.tims.knowledge.mapper.SysAuthMapper;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * M6 抽取审核中心（仅 ADMIN 可审核）。
 * 用户拍板口径：任何情况下不自动合并、不自动覆盖；系统只给建议，落库/合并/驳回均须人工点击。
 * 合并前写入 kb_knowledge_history 全量快照并追加正文，保留原条目历史与合并引用关系。
 */
@Service
public class ExtractionReviewService {

    private static final ObjectMapper MAPPER = new ObjectMapper();
    private static final Set<String> PENDING_STATUS = Set.of("PENDING_REVIEW", "MANUAL_REQUIRED");

    private final AiExtractedMapper extractedMapper;
    private final KbKnowledgeMapper knowledgeMapper;
    private final KbKnowledgeHistoryMapper historyMapper;
    private final SysAuthMapper sysAuthMapper;

    public ExtractionReviewService(AiExtractedMapper extractedMapper,
                                   KbKnowledgeMapper knowledgeMapper,
                                   KbKnowledgeHistoryMapper historyMapper,
                                   SysAuthMapper sysAuthMapper) {
        this.extractedMapper = extractedMapper;
        this.knowledgeMapper = knowledgeMapper;
        this.historyMapper = historyMapper;
        this.sysAuthMapper = sysAuthMapper;
    }

    public Page<AiExtracted> page(long current, long size, String status) {
        LambdaQueryWrapper<AiExtracted> w = new LambdaQueryWrapper<AiExtracted>()
                .eq(status != null && !status.isBlank(), AiExtracted::getStatus, status)
                .orderByDesc(AiExtracted::getCreateTime);
        Page<AiExtracted> page = extractedMapper.selectPage(new Page<>(current, size), w);
        fillTargetTitle(page.getRecords());
        return page;
    }

    public AiExtracted detail(Long id) {
        AiExtracted row = extractedMapper.selectById(id);
        if (row == null) {
            throw new BizException(30404, "抽取记录不存在");
        }
        if (row.getDedupTargetId() != null) {
            KbKnowledge target = knowledgeMapper.selectById(row.getDedupTargetId());
            row.setDedupTargetTitle(target == null ? null : target.getTitle());
        }
        return row;
    }

    /** 人工补录：仅待审核/待补录记录可编辑，补录后转为待审核 */
    public AiExtracted update(Long id, AiExtracted in) {
        AiExtracted row = detail(id);
        requirePending(row, "编辑");
        if (in.getTitle() != null) row.setTitle(in.getTitle());
        if (in.getDeviceType() != null) row.setDeviceType(in.getDeviceType());
        if (in.getFaultPhenomenon() != null) row.setFaultPhenomenon(in.getFaultPhenomenon());
        if (in.getTroubleshootSteps() != null) row.setTroubleshootSteps(in.getTroubleshootSteps());
        if (in.getSolutionSteps() != null) row.setSolutionSteps(in.getSolutionSteps());
        if (in.getKeyPoints() != null) row.setKeyPoints(in.getKeyPoints());
        if (in.getTags() != null) row.setTags(validateTags(in.getTags()));
        if ("MANUAL_REQUIRED".equals(row.getStatus())) {
            row.setStatus("PENDING_REVIEW");
            row.setErrorMsg(null);
        }
        row.setUpdateTime(LocalDateTime.now());
        extractedMapper.updateById(row);
        return row;
    }

    /**
     * 人工确认“新建”：写入 kb_knowledge（PUBLISHED），向量同步任务 10s 内接管并入库 Milvus。
     */
    @Transactional
    public KbKnowledge approve(Long id) {
        requireAdmin();
        AiExtracted row = detail(id);
        requirePending(row, "通过");
        if (row.getTitle() == null || row.getTitle().isBlank()) {
            throw new BizException(10400, "标题必填，请先补录后再通过");
        }
        KbKnowledge k = new KbKnowledge();
        k.setTenantId(row.getTenantId());
        k.setTitle(row.getTitle());
        k.setContent(buildContent(row));
        k.setSummary(truncate(row.getFaultPhenomenon() == null || row.getFaultPhenomenon().isBlank()
                ? row.getTitle() : row.getFaultPhenomenon(), 500));
        k.setTags(row.getTags() == null || row.getTags().isBlank() ? "[]" : validateTags(row.getTags()));
        k.setApplyDeviceType(row.getDeviceType());
        k.setCategoryId(1L);
        k.setSourceTicketId(row.getSourceTicketId());
        k.setStatus("PUBLISHED");
        k.setVersion(1);
        k.setQuoteCount(0);
        k.setCreateBy(StpUtil.getLoginIdAsLong());
        k.setCreateTime(LocalDateTime.now());
        k.setUpdateTime(LocalDateTime.now());
        knowledgeMapper.insert(k);

        row.setStatus("APPROVED");
        row.setKnowledgeId(k.getId());
        row.setReviewBy(StpUtil.getLoginIdAsLong());
        row.setReviewTime(LocalDateTime.now());
        row.setUpdateTime(LocalDateTime.now());
        extractedMapper.updateById(row);
        return k;
    }

    /**
     * 人工确认“合并”：必须先写历史快照，再追加正文/合并标签，绝不覆盖原内容。
     */
    @Transactional
    public KbKnowledge merge(Long id, Long targetId) {
        requireAdmin();
        AiExtracted row = detail(id);
        requirePending(row, "合并");
        Long tid = targetId != null ? targetId : row.getDedupTargetId();
        if (tid == null) {
            throw new BizException(10400, "未指定合并目标条目");
        }
        KbKnowledge target = knowledgeMapper.selectById(tid);
        if (target == null) {
            throw new BizException(30404, "合并目标条目不存在");
        }
        if (!"PUBLISHED".equals(target.getStatus())) {
            throw new BizException(30401, "仅可合并到已发布条目");
        }

        KbKnowledgeHistory h = new KbKnowledgeHistory();
        h.setTenantId(target.getTenantId());
        h.setKnowledgeId(target.getId());
        h.setVersion(target.getVersion());
        h.setTitle(target.getTitle());
        h.setContent(target.getContent());
        h.setSummary(target.getSummary());
        h.setTags(target.getTags());
        h.setApplyDeviceType(target.getApplyDeviceType());
        h.setChangeType("MERGE");
        h.setSourceExtractedId(row.getId());
        h.setCreateBy(StpUtil.getLoginIdAsLong());
        h.setCreateTime(LocalDateTime.now());
        historyMapper.insert(h);

        String append = buildContent(row);
        target.setContent((target.getContent() == null ? "" : target.getContent())
                + "\n\n【工单补充 " + (row.getSourceTicketNo() == null ? "" : row.getSourceTicketNo()) + "】\n" + append);
        target.setTags(unionTags(target.getTags(), row.getTags()));
        target.setVersion((target.getVersion() == null ? 1 : target.getVersion()) + 1);
        target.setUpdateTime(LocalDateTime.now());
        knowledgeMapper.updateById(target);

        row.setStatus("MERGED");
        row.setKnowledgeId(target.getId());
        row.setReviewBy(StpUtil.getLoginIdAsLong());
        row.setReviewTime(LocalDateTime.now());
        row.setUpdateTime(LocalDateTime.now());
        extractedMapper.updateById(row);
        return target;
    }

    /** 人工确认“跳过/驳回”：仅记录，不写知识库 */
    public void reject(Long id, String reason) {
        requireAdmin();
        AiExtracted row = detail(id);
        requirePending(row, "驳回");
        row.setStatus("REJECTED");
        row.setRejectReason(reason == null || reason.isBlank() ? "人工驳回" : reason);
        row.setReviewBy(StpUtil.getLoginIdAsLong());
        row.setReviewTime(LocalDateTime.now());
        row.setUpdateTime(LocalDateTime.now());
        extractedMapper.updateById(row);
    }

    /** 合并留痕查询：某知识条目的历史版本 */
    public List<KbKnowledgeHistory> history(Long knowledgeId) {
        return historyMapper.selectList(new LambdaQueryWrapper<KbKnowledgeHistory>()
                .eq(KbKnowledgeHistory::getKnowledgeId, knowledgeId)
                .orderByDesc(KbKnowledgeHistory::getCreateTime));
    }

    private void fillTargetTitle(List<AiExtracted> rows) {
        Set<Long> ids = new HashSet<>();
        for (AiExtracted r : rows) {
            if (r.getDedupTargetId() != null) {
                ids.add(r.getDedupTargetId());
            }
        }
        if (ids.isEmpty()) {
            return;
        }
        Map<Long, KbKnowledge> map = new java.util.HashMap<>();
        knowledgeMapper.selectBatchIds(ids).forEach(k -> map.put(k.getId(), k));
        for (AiExtracted r : rows) {
            KbKnowledge k = map.get(r.getDedupTargetId());
            if (k != null) {
                r.setDedupTargetTitle(k.getTitle());
            }
        }
    }

    private void requirePending(AiExtracted row, String action) {
        if (!PENDING_STATUS.contains(row.getStatus())) {
            throw new BizException(30401, "非法状态迁移: " + row.getStatus() + " 不能执行 " + action);
        }
    }

    private String buildContent(AiExtracted row) {
        StringBuilder sb = new StringBuilder();
        sb.append("故障现象：").append(nvl(row.getFaultPhenomenon())).append('\n');
        if (!nvl(row.getTroubleshootSteps()).isBlank()) {
            sb.append("排查步骤：\n").append(row.getTroubleshootSteps()).append('\n');
        }
        sb.append("解决步骤：\n").append(nvl(row.getSolutionSteps())).append('\n');
        if (!nvl(row.getKeyPoints()).isBlank()) {
            sb.append("关键要点：\n").append(row.getKeyPoints()).append('\n');
        }
        return sb.toString().trim();
    }

    private String unionTags(String oldJson, String newJson) {
        LinkedHashSet<String> set = new LinkedHashSet<>(parseTags(oldJson));
        set.addAll(parseTags(newJson));
        try {
            return MAPPER.writeValueAsString(new ArrayList<>(set));
        } catch (Exception e) {
            return oldJson == null || oldJson.isBlank() ? "[]" : oldJson;
        }
    }

    private List<String> parseTags(String json) {
        List<String> list = new ArrayList<>();
        if (json == null || json.isBlank()) {
            return list;
        }
        try {
            JsonNode n = MAPPER.readTree(json);
            if (n.isArray()) {
                n.forEach(x -> {
                    if (!x.asText("").isBlank()) {
                        list.add(x.asText());
                    }
                });
            }
        } catch (Exception ignored) {
            // 非法 JSON 视为无标签
        }
        return list;
    }

    private String validateTags(String json) {
        try {
            JsonNode n = MAPPER.readTree(json);
            if (!n.isArray()) {
                throw new BizException(10400, "标签必须是 JSON 数组");
            }
            return MAPPER.writeValueAsString(n);
        } catch (BizException e) {
            throw e;
        } catch (Exception e) {
            throw new BizException(10400, "标签必须是合法 JSON 数组");
        }
    }

    private void requireAdmin() {
        long userId = StpUtil.getLoginIdAsLong();
        Long tenantId = com.tims.knowledge.config.TenantContext.resolve();
        List<String> roles = sysAuthMapper.selectRoleCodes(tenantId, userId);
        if (roles == null || !roles.contains("ADMIN")) {
            throw new BizException(10403, "仅 ADMIN 可审核抽取结果");
        }
    }

    private static String nvl(String s) {
        return s == null ? "" : s;
    }

    private static String truncate(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max);
    }
}
