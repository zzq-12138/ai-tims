package com.tims.knowledge.service;

import com.tims.knowledge.entity.KbKnowledge;
import io.milvus.client.MilvusServiceClient;
import io.milvus.param.ConnectParam;
import io.milvus.param.IndexType;
import io.milvus.param.MetricType;
import io.milvus.param.R;
import io.milvus.param.collection.CreateCollectionParam;
import io.milvus.param.collection.FieldType;
import io.milvus.param.collection.FlushParam;
import io.milvus.param.collection.HasCollectionParam;
import io.milvus.param.collection.LoadCollectionParam;
import io.milvus.param.dml.DeleteParam;
import io.milvus.param.dml.InsertParam;
import io.milvus.param.dml.SearchParam;
import io.milvus.param.index.CreateIndexParam;
import io.milvus.response.QueryResultsWrapper;
import io.milvus.response.SearchResultsWrapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import jakarta.annotation.PreDestroy;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;

/**
 * Milvus 向量存取封装（M3）。
 * - collection 惰性创建：kb_knowledge_vec（knowledge_id 主键 + tenant_id/device_type 标量 + embedding FLOAT_VECTOR）。
 * - Milvus 不可用时 isAvailable()=false，检索侧降级纯关键词（fallback 标记），
 *   同步任务跳过本轮、不更新 synced_at，恢复后自动补同步。
 */
@Service
public class MilvusVectorStore {

    private static final Logger log = LoggerFactory.getLogger(MilvusVectorStore.class);

    @Value("${tims.kb.milvus.host:127.0.0.1}")
    private String host;

    @Value("${tims.kb.milvus.port:19530}")
    private int port;

    @Value("${tims.kb.milvus.collection:kb_knowledge_vec}")
    private String collection;

    @Value("${tims.kb.embedding.dimensions:1024}")
    private int dimensions;

    private final AtomicReference<MilvusServiceClient> clientRef = new AtomicReference<>();
    private final AtomicReference<Long> lastFailAt = new AtomicReference<>(0L);
    private static final long RETRY_BACKOFF_MS = 30_000;

    /** Milvus 是否可用（失败后 30s 内不再重试，避免同步任务每 10s 卡在连接超时） */
    public boolean isAvailable() {
        if (System.currentTimeMillis() - lastFailAt.get() < RETRY_BACKOFF_MS) {
            return false;
        }
        try {
            MilvusServiceClient c = ensureClient();
            R<Boolean> r = c.hasCollection(HasCollectionParam.newBuilder()
                    .withCollectionName(collection).build());
            return r.getStatus() == R.Status.Success.getCode();
        } catch (Exception e) {
            lastFailAt.set(System.currentTimeMillis());
            closeQuietly();
            log.warn("[milvus] 不可用: {}", e.getMessage());
            return false;
        }
    }

    /** 集合不存在则创建（pk + 标量 + 向量，HNSW/COSINE）并 load */
    public void ensureCollection() {
        MilvusServiceClient c = ensureClient();
        R<Boolean> has = c.hasCollection(HasCollectionParam.newBuilder()
                .withCollectionName(collection).build());
        if (has.getStatus() == R.Status.Success.getCode() && Boolean.TRUE.equals(has.getData())) {
            return;
        }
        CreateCollectionParam create = CreateCollectionParam.newBuilder()
                .withCollectionName(collection)
                .withDescription("AI-TIMS knowledge vectors (M3)")
                .withShardsNum(1)
                .addFieldType(FieldType.newBuilder()
                        .withName("knowledge_id").withDataType(io.milvus.grpc.DataType.Int64)
                        .withPrimaryKey(true).withAutoID(false).build())
                .addFieldType(FieldType.newBuilder()
                        .withName("tenant_id").withDataType(io.milvus.grpc.DataType.Int64).build())
                .addFieldType(FieldType.newBuilder()
                        .withName("device_type").withDataType(io.milvus.grpc.DataType.VarChar)
                        .withMaxLength(64).build())
                .addFieldType(FieldType.newBuilder()
                        .withName("embedding").withDataType(io.milvus.grpc.DataType.FloatVector)
                        .withDimension(dimensions).build())
                .build();
        R<?> cr = c.createCollection(create);
        check(cr, "createCollection");

        R<?> ir = c.createIndex(CreateIndexParam.newBuilder()
                .withCollectionName(collection)
                .withFieldName("embedding")
                .withIndexType(IndexType.HNSW)
                .withMetricType(MetricType.COSINE)
                .withExtraParam("{\"M\":8,\"efConstruction\":64}")
                .build());
        check(ir, "createIndex");

        R<?> lr = c.loadCollection(LoadCollectionParam.newBuilder()
                .withCollectionName(collection).build());
        check(lr, "loadCollection");
        log.info("[milvus] collection {} 创建完成 dim={}", collection, dimensions);
    }

    /** 批量 upsert（先按主键删再插，Milvus 2.4 无原生 upsert 于 V1 API 场景下最稳） */
    public void upsert(List<KbKnowledge> docs, List<float[]> vectors) {
        if (docs.isEmpty()) return;
        MilvusServiceClient c = ensureClient();
        ensureCollection();

        List<Long> ids = docs.stream().map(KbKnowledge::getId).toList();
        // 先删旧向量（编辑重发场景）
        c.delete(DeleteParam.newBuilder()
                .withCollectionName(collection)
                .withExpr("knowledge_id in " + ids.toString())
                .build());

        List<InsertParam.Field> fields = new ArrayList<>();
        fields.add(new InsertParam.Field("knowledge_id", ids));
        fields.add(new InsertParam.Field("tenant_id", docs.stream().map(KbKnowledge::getTenantId).toList()));
        fields.add(new InsertParam.Field("device_type", docs.stream()
                .map(k -> k.getApplyDeviceType() == null ? "" : k.getApplyDeviceType()).toList()));
        List<List<Float>> vecs = new ArrayList<>(vectors.size());
        for (float[] v : vectors) {
            List<Float> l = new ArrayList<>(v.length);
            for (float x : v) l.add(x);
            vecs.add(l);
        }
        fields.add(new InsertParam.Field("embedding", vecs));

        R<?> r = c.insert(InsertParam.newBuilder()
                .withCollectionName(collection)
                .withFields(fields)
                .build());
        check(r, "insert");
        c.flush(FlushParam.newBuilder().withCollectionNames(List.of(collection)).build());
    }

    /** 向量检索，返回 knowledge_id + 相似度得分（按得分降序） */
    public List<VecHit> search(float[] queryVector, int topK, Long tenantId) {
        MilvusServiceClient c = ensureClient();
        List<Float> q = new ArrayList<>(queryVector.length);
        for (float x : queryVector) q.add(x);
        SearchParam sp = SearchParam.newBuilder()
                .withCollectionName(collection)
                .withMetricType(MetricType.COSINE)
                .withVectorFieldName("embedding")
                .withVectors(Collections.singletonList(q))
                .withTopK(topK)
                .withExpr("tenant_id == " + tenantId)
                .withParams("{\"ef\":64}")
                .build();
        R<io.milvus.grpc.SearchResults> r = c.search(sp);
        check(r, "search");
        // 用 IDScore 解析（2.4.4 的 getRowRecords 依赖 outFields 名匹配，易抛 key not found；
        // 设备类型等详情统一由调用方回查 MySQL，此处不取标量字段）
        SearchResultsWrapper wrapper = new SearchResultsWrapper(r.getData().getResults());
        List<SearchResultsWrapper.IDScore> idScores = wrapper.getIDScore(0);
        List<VecHit> hits = new ArrayList<>(idScores.size());
        for (SearchResultsWrapper.IDScore s : idScores) {
            hits.add(new VecHit(s.getLongID(), (float) s.getScore(), null));
        }
        return hits;
    }

    /** 按知识点主键删除向量（知识删除/驳回下架时调用，尽力而为） */
    public void deleteByKnowledgeIds(List<Long> ids) {
        if (ids == null || ids.isEmpty()) return;
        try {
            MilvusServiceClient c = ensureClient();
            c.delete(DeleteParam.newBuilder()
                    .withCollectionName(collection)
                    .withExpr("knowledge_id in " + ids.toString())
                    .build());
        } catch (Exception e) {
            log.warn("[milvus] 删除向量失败（下轮同步/重建兜底）: {}", e.getMessage());
        }
    }

    private MilvusServiceClient ensureClient() {
        MilvusServiceClient c = clientRef.get();
        if (c != null) return c;
        synchronized (this) {
            if (clientRef.get() == null) {
                c = new MilvusServiceClient(ConnectParam.newBuilder()
                        .withHost(host)
                        .withPort(port)
                        // M4：推送链路 P95 ≤ 1s，降级必须快速失败——
                        // docker stop 后 docker-proxy 仍可能短暂 accept 连接，
                        // connect deadline 1s + rpc deadline 1s，保证 kb 侧 ~1s 内退关键词兜底
                        .withConnectTimeout(1, java.util.concurrent.TimeUnit.SECONDS)
                        .withRpcDeadline(1, java.util.concurrent.TimeUnit.SECONDS)
                        .build());
                clientRef.set(c);
            }
            return clientRef.get();
        }
    }

    private void check(R<?> r, String op) {
        if (r.getStatus() != R.Status.Success.getCode()) {
            lastFailAt.set(System.currentTimeMillis());
            closeQuietly();
            throw new IllegalStateException("milvus " + op + " 失败: " + r.getMessage());
        }
    }

    private void closeQuietly() {
        MilvusServiceClient c = clientRef.getAndSet(null);
        if (c != null) {
            try {
                c.close();
            } catch (Exception ignored) {
            }
        }
    }

    @PreDestroy
    public void shutdown() {
        closeQuietly();
    }

    /** 向量命中项 */
    public record VecHit(Long knowledgeId, float score, String deviceType) {
    }
}
