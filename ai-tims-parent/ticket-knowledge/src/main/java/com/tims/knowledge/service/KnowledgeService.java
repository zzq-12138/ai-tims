package com.tims.knowledge.service;

import cn.dev33.satoken.stp.StpUtil;
import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.tims.common.exception.BizException;
import com.tims.knowledge.entity.KbKnowledge;
import com.tims.knowledge.mapper.KbKnowledgeMapper;
import com.tims.knowledge.mapper.SysAuthMapper;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Set;

/**
 * 知识 CRUD + 审核流（M3）。
 * 状态机：DRAFT →(submit)→ PENDING →(publish/reject)→ PUBLISHED/REJECTED；
 * REJECTED 可编辑后重新 submit。知识 30xxx 段错误码：30401 非法迁移 / 30404 不存在。
 */
@Service
public class KnowledgeService {

    /** 知识状态合法迁移表 */
    private static final Set<String> VALID_STATUS = Set.of("DRAFT", "PENDING", "PUBLISHED", "REJECTED");

    private final KbKnowledgeMapper knowledgeMapper;
    private final SysAuthMapper sysAuthMapper;
    private final MilvusVectorStore vectorStore;

    public KnowledgeService(KbKnowledgeMapper knowledgeMapper,
                            SysAuthMapper sysAuthMapper,
                            MilvusVectorStore vectorStore) {
        this.knowledgeMapper = knowledgeMapper;
        this.sysAuthMapper = sysAuthMapper;
        this.vectorStore = vectorStore;
    }

    /** 分页查询（status/deviceType/categoryId/keyword 过滤） */
    public Page<KbKnowledge> page(long current, long size, String status,
                                  String deviceType, Long categoryId, String keyword) {
        LambdaQueryWrapper<KbKnowledge> w = new LambdaQueryWrapper<KbKnowledge>()
                .eq(StringUtils.hasText(status), KbKnowledge::getStatus, status)
                .eq(StringUtils.hasText(deviceType), KbKnowledge::getApplyDeviceType, deviceType)
                .eq(categoryId != null, KbKnowledge::getCategoryId, categoryId)
                .and(StringUtils.hasText(keyword), x -> x
                        .like(KbKnowledge::getTitle, keyword)
                        .or()
                        .like(KbKnowledge::getContent, keyword))
                .orderByDesc(KbKnowledge::getUpdateTime);
        return knowledgeMapper.selectPage(new Page<>(current, size), w);
    }

    public KbKnowledge detail(Long id) {
        KbKnowledge k = knowledgeMapper.selectById(id);
        if (k == null) {
            throw new BizException(30404, "知识不存在");
        }
        return k;
    }

    public KbKnowledge create(KbKnowledge in) {
        validate(in);
        in.setId(null);
        in.setStatus("DRAFT");
        in.setVersion(1);
        in.setQuoteCount(0);
        in.setCreateBy(StpUtil.getLoginIdAsLong());
        in.setCreateTime(null);
        in.setUpdateTime(null);
        knowledgeMapper.insert(in);
        return in;
    }

    /** 编辑：任意状态可改，version+1；PUBLISHED 编辑后 update_time > synced_at，同步任务自动重嵌 */
    public KbKnowledge update(Long id, KbKnowledge in) {
        KbKnowledge exist = detail(id);
        validate(in);
        exist.setTitle(in.getTitle());
        exist.setContent(in.getContent());
        exist.setSummary(in.getSummary());
        exist.setTags(in.getTags());
        exist.setApplyDeviceType(in.getApplyDeviceType());
        exist.setCategoryId(in.getCategoryId());
        exist.setVersion(exist.getVersion() + 1);
        knowledgeMapper.updateById(exist);
        return exist;
    }

    /** 逻辑删除 + 尽力删除 Milvus 向量 */
    public void delete(Long id) {
        detail(id);
        knowledgeMapper.deleteById(id);
        vectorStore.deleteByKnowledgeIds(List.of(id));
    }

    /** DRAFT/REJECTED → PENDING（提交审核） */
    public void submit(Long id) {
        KbKnowledge k = detail(id);
        requireTransition(k, "submit", Set.of("DRAFT", "REJECTED"), "PENDING");
        k.setStatus("PENDING");
        k.setRejectReason(null);
        knowledgeMapper.updateById(k);
    }

    /** PENDING → PUBLISHED（仅 ADMIN），入库即进入向量同步队列 */
    public void publish(Long id) {
        requireAdmin();
        KbKnowledge k = detail(id);
        requireTransition(k, "publish", Set.of("PENDING"), "PUBLISHED");
        k.setStatus("PUBLISHED");
        knowledgeMapper.updateById(k);
    }

    /** PENDING → REJECTED（仅 ADMIN），同步撤下向量（不可检索） */
    public void reject(Long id, String reason) {
        requireAdmin();
        KbKnowledge k = detail(id);
        requireTransition(k, "reject", Set.of("PENDING"), "REJECTED");
        k.setStatus("REJECTED");
        k.setRejectReason(reason);
        knowledgeMapper.updateById(k);
        vectorStore.deleteByKnowledgeIds(List.of(id));
    }

    private void validate(KbKnowledge in) {
        if (!StringUtils.hasText(in.getTitle()) || in.getTitle().length() > 128) {
            throw new BizException(10400, "标题必填且 ≤128 字");
        }
        if (!StringUtils.hasText(in.getContent())) {
            throw new BizException(10400, "正文必填");
        }
        if (StringUtils.hasText(in.getStatus()) && !VALID_STATUS.contains(in.getStatus())) {
            throw new BizException(10400, "非法状态值");
        }
    }

    private void requireTransition(KbKnowledge k, String action, Set<String> from, String to) {
        if (!from.contains(k.getStatus())) {
            throw new BizException(30401,
                    "非法状态迁移: " + k.getStatus() + " 不能执行 " + action + "（目标 " + to + "）");
        }
    }

    private void requireAdmin() {
        long userId = StpUtil.getLoginIdAsLong();
        Long tenantId = com.tims.knowledge.config.TenantContext.resolve();
        List<String> roles = sysAuthMapper.selectRoleCodes(tenantId, userId);
        if (roles == null || !roles.contains("ADMIN")) {
            throw new BizException(10403, "仅 ADMIN 可审核知识");
        }
    }
}
