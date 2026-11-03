package com.tims.knowledge.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.knowledge.entity.KbKnowledge;
import com.tims.knowledge.mapper.KbKnowledgeMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 知识向量增量同步任务（M3）。
 * 每 10s 扫描：PUBLISHED 且（vector_synced_at IS NULL 或 update_time > vector_synced_at）的知识，
 * 批量向量化（≤16 条/批）后 upsert 进 Milvus，回写 vector_synced_at。
 * 保证：知识发布后 30s 内可被向量检索命中。
 * 降级：Milvus 不可用/向量化失败 → warn 日志、跳过本轮、不更新 synced_at，下一轮自动重试。
 */
@Service
public class VectorSyncService {

    private static final Logger log = LoggerFactory.getLogger(VectorSyncService.class);

    private final KbKnowledgeMapper knowledgeMapper;
    private final EmbeddingService embeddingService;
    private final MilvusVectorStore vectorStore;

    @Value("${tims.kb.sync.batch-size:16}")
    private int batchSize;

    public VectorSyncService(KbKnowledgeMapper knowledgeMapper,
                             EmbeddingService embeddingService,
                             MilvusVectorStore vectorStore) {
        this.knowledgeMapper = knowledgeMapper;
        this.embeddingService = embeddingService;
        this.vectorStore = vectorStore;
    }

    @Scheduled(fixedDelayString = "${tims.kb.sync.interval-ms:10000}", initialDelay = 8_000)
    public void sync() {
        if (!embeddingService.isConfigured()) {
            return; // 未配 key（本地开发静默跳过）
        }
        List<KbKnowledge> pending = knowledgeMapper.selectList(new LambdaQueryWrapper<KbKnowledge>()
                .eq(KbKnowledge::getStatus, "PUBLISHED")
                .and(w -> w.isNull(KbKnowledge::getVectorSyncedAt)
                        .or()
                        .apply("update_time > vector_synced_at"))
                .orderByAsc(KbKnowledge::getUpdateTime)
                .last("LIMIT " + batchSize));
        if (pending.isEmpty()) {
            return;
        }
        try {
            List<String> texts = pending.stream()
                    .map(k -> k.getTitle() + "\n" + (k.getSummary() == null ? "" : k.getSummary() + "\n") + k.getContent())
                    .toList();
            List<float[]> vectors = embeddingService.embed(texts);
            vectorStore.upsert(pending, vectors);
            LocalDateTime now = LocalDateTime.now();
            for (KbKnowledge k : pending) {
                KbKnowledge patch = new KbKnowledge();
                patch.setId(k.getId());
                patch.setVectorSyncedAt(now);
                knowledgeMapper.updateById(patch);
            }
            log.info("[vector-sync] 同步 {} 条知识进 Milvus", pending.size());
        } catch (Exception e) {
            log.warn("[vector-sync] 本轮同步失败，下轮重试: {}", e.getMessage());
        }
    }
}
