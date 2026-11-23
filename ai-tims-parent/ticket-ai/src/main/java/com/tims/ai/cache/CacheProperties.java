package com.tims.ai.cache;

import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * 语义缓存配置（tims.ai.cache）。默认关闭，关闭时 ChatService 不查缓存、不落缓存，
 * 接口契约与调用行为与改动前完全一致。
 */
@Component
@ConfigurationProperties(prefix = "tims.ai.cache")
public class CacheProperties {

    /** 总开关；关闭时零开销（不调 embedding、不改响应） */
    private boolean enabled = false;

    /** 余弦相似度阈值：≥ 阈值才认为语义命中 */
    private double threshold = 0.92;

    /** 条目存活时间（秒），默认 1 天 */
    private int ttlSeconds = 86_400;

    /** 单租户最大条目数，超出按最旧淘汰 */
    private int maxEntries = 2_000;

    /** 向量模型（智谱 OpenAI 兼容端点） */
    private String embeddingModel = "embedding-3";

    /** 向量接口路径 */
    private String embeddingsPath = "/embeddings";

    /** 低于该字符数的问题不缓存（避免“好”“嗯”这类噪声占满缓存） */
    private int minQuestionChars = 6;

    /** embedding 请求超时（ms）；超时按未命中处理，不阻断问答 */
    private int embeddingTimeoutMs = 3_000;

    public boolean isEnabled() { return enabled; }
    public void setEnabled(boolean enabled) { this.enabled = enabled; }
    public double getThreshold() { return threshold; }
    public void setThreshold(double threshold) { this.threshold = threshold; }
    public int getTtlSeconds() { return ttlSeconds; }
    public void setTtlSeconds(int ttlSeconds) { this.ttlSeconds = ttlSeconds; }
    public int getMaxEntries() { return maxEntries; }
    public void setMaxEntries(int maxEntries) { this.maxEntries = maxEntries; }
    public String getEmbeddingModel() { return embeddingModel; }
    public void setEmbeddingModel(String embeddingModel) { this.embeddingModel = embeddingModel; }
    public String getEmbeddingsPath() { return embeddingsPath; }
    public void setEmbeddingsPath(String embeddingsPath) { this.embeddingsPath = embeddingsPath; }
    public int getMinQuestionChars() { return minQuestionChars; }
    public void setMinQuestionChars(int minQuestionChars) { this.minQuestionChars = minQuestionChars; }
    public int getEmbeddingTimeoutMs() { return embeddingTimeoutMs; }
    public void setEmbeddingTimeoutMs(int embeddingTimeoutMs) { this.embeddingTimeoutMs = embeddingTimeoutMs; }
}
