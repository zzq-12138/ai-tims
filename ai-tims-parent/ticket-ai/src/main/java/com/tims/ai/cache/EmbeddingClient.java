package com.tims.ai.cache;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.ai.config.AiProperties;
import com.tims.ai.llm.ZhipuKeyProvider;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 智谱 embedding 客户端（OpenAI 兼容 /embeddings）。失败一律返回 null，
 * 由调用方按“未命中”处理，缓存不可用不影响正常问答。
 */
@Component
public class EmbeddingClient {

    private static final Logger log = LoggerFactory.getLogger(EmbeddingClient.class);

    private final AiProperties props;
    private final CacheProperties cacheProps;
    private final ZhipuKeyProvider keyProvider;
    private final ObjectMapper mapper;
    private final HttpClient httpClient = HttpClient.newBuilder()
            // 与 ZhipuStreamClient 同理：避免对 http:// 端点发 h2c 升级导致请求体被丢
            .version(HttpClient.Version.HTTP_1_1)
            .connectTimeout(Duration.ofSeconds(2))
            .build();

    public EmbeddingClient(AiProperties props, CacheProperties cacheProps,
                           ZhipuKeyProvider keyProvider, ObjectMapper mapper) {
        this.props = props;
        this.cacheProps = cacheProps;
        this.keyProvider = keyProvider;
        this.mapper = mapper;
    }

    /** 返回问题向量；不可用时返回 null（调用方按未命中处理） */
    public double[] embed(String text) {
        if (text == null || text.isBlank()) {
            return null;
        }
        String key = keyProvider.getKey();
        if (key.isEmpty()) {
            return null;
        }
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("model", cacheProps.getEmbeddingModel());
        body.put("input", List.of(text));
        try {
            HttpRequest req = HttpRequest.newBuilder(
                            URI.create(props.getBaseUrl() + cacheProps.getEmbeddingsPath()))
                    .timeout(Duration.ofMillis(cacheProps.getEmbeddingTimeoutMs()))
                    .header("Authorization", "Bearer " + key)
                    .header("Content-Type", "application/json")
                    .POST(HttpRequest.BodyPublishers.ofString(
                            mapper.writeValueAsString(body), StandardCharsets.UTF_8))
                    .build();
            HttpResponse<String> resp = httpClient.send(req,
                    HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8));
            if (resp.statusCode() / 100 != 2) {
                log.warn("[cache] embedding HTTP {}，按未命中处理", resp.statusCode());
                return null;
            }
            JsonNode root = mapper.readTree(resp.body());
            JsonNode arr = root.path("data").path(0).path("embedding");
            if (!arr.isArray() || arr.isEmpty()) {
                return null;
            }
            double[] vec = new double[arr.size()];
            for (int i = 0; i < arr.size(); i++) {
                vec[i] = arr.get(i).asDouble();
            }
            return vec;
        } catch (Exception e) {
            log.warn("[cache] embedding 调用失败，按未命中处理: {}", e.getMessage());
            return null;
        }
    }
}
