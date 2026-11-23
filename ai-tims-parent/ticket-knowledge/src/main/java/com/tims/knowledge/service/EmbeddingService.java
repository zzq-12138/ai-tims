package com.tims.knowledge.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestClient;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 向量化客户端（M3）：OpenAI 兼容 /v1/embeddings，批量入参（≤64）。
 * 地址/模型/维度均从配置读取：开发环境为智谱 embedding-3（1024 维），
 * 公司环境为公司 vLLM 的 Qwen/Qwen3-Embedding-8B（1024 维）。
 * key 从环境变量注入（~/secrets），不进 git。
 */
@Service
public class EmbeddingService {

    @Value("${tims.kb.embedding.api-url}")
    private String apiUrl;

    @Value("${tims.kb.embedding.api-key}")
    private String apiKey;

    @Value("${tims.kb.embedding.model}")
    private String model;

    @Value("${tims.kb.embedding.dimensions}")
    private int dimensions;

    @Value("${tims.kb.embedding.max-text-length:4000}")
    private int maxTextLength;

    /**
     * Qwen3-Embedding 查询侧检索指令（任务描述，不含 Instruct:/Query: 包装）。
     * 留空 = 不加前缀，与旧行为完全一致；文档侧始终走原文本，不加前缀。
     */
    @Value("${tims.kb.embedding.query-instruction:}")
    private String queryInstruction;

    private final ObjectMapper objectMapper = new ObjectMapper();

    private final UsageReporter usageReporter;

    private volatile RestClient restClient;

    public EmbeddingService(UsageReporter usageReporter) {
        this.usageReporter = usageReporter;
    }

    /**
     * 批量向量化。入参顺序与返回向量顺序一一对应。
     * 调用方保证 texts 非空且 ≤64 条（同步任务按 batch-size=16 切批）。
     */
    public List<float[]> embed(List<String> texts) {
        if (texts == null || texts.isEmpty()) {
            return List.of();
        }
        RestClient client = ensureClient();
        long startedAt = System.currentTimeMillis();
        List<String> trimmed = texts.stream().map(t -> t == null ? "" : truncate(t)).toList();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("model", model);
        body.put("input", trimmed);
        body.put("dimensions", dimensions);

        String resp = client.post()
                .uri(apiUrl)
                .contentType(MediaType.APPLICATION_JSON)
                .header("Authorization", "Bearer " + apiKey)
                .body(body)
                .retrieve()
                .body(String.class);

        try {
            JsonNode root = objectMapper.readTree(resp);
            JsonNode data = root.get("data");
            if (data == null || !data.isArray() || data.size() != trimmed.size()) {
                throw new IllegalStateException("embedding 返回条数不匹配: "
                        + (data == null ? "null" : data.size()) + " vs " + trimmed.size());
            }
            // M6：用量回传（批量按 1 条记，tokens 取响应 usage.prompt_tokens）
            JsonNode usage = root.get("usage");
            int promptTokens = usage != null && usage.get("prompt_tokens") != null
                    ? usage.get("prompt_tokens").asInt() : 0;
            usageReporter.report("EMBED", model, promptTokens, System.currentTimeMillis() - startedAt);

            List<float[]> result = new ArrayList<>(trimmed.size());
            for (JsonNode item : data) {
                JsonNode vec = item.get("embedding");
                float[] v = new float[vec.size()];
                for (int i = 0; i < vec.size(); i++) {
                    v[i] = (float) vec.get(i).asDouble();
                }
                result.add(v);
            }
            return result;
        } catch (Exception e) {
            if (e instanceof IllegalStateException ise) throw ise;
            throw new IllegalStateException("embedding 响应解析失败: " + e.getMessage(), e);
        }
    }

    /**
     * 查询侧向量化：Qwen3-Embedding 检索协议要求查询加 instruction、文档不加。
     * 配置了 tims.kb.embedding.query-instruction 时拼成 "Instruct: {desc}\nQuery: {query}"；
     * 未配置时退化为原文本，行为与改造前一致（可随时回滚）。
     */
    public float[] embedQuery(String query) {
        String q = query == null ? "" : query;
        if (!StringUtils.hasText(queryInstruction)) {
            return embed(List.of(q)).get(0);
        }
        return embed(List.of("Instruct: " + queryInstruction.trim() + "\nQuery: " + q)).get(0);
    }

    /** 服务可用性探测（配置是否齐备），供同步任务降级判断 */
    public boolean isConfigured() {
        return apiKey != null && !apiKey.isBlank();
    }

    private String truncate(String t) {
        return t.length() <= maxTextLength ? t : t.substring(0, maxTextLength);
    }

    private RestClient ensureClient() {
        RestClient c = restClient;
        if (c == null) {
            synchronized (this) {
                if (restClient == null) {
                    restClient = RestClient.builder()
                            .requestFactory(new org.springframework.http.client.SimpleClientHttpRequestFactory() {{
                                setConnectTimeout(5_000);
                                setReadTimeout(30_000);
                            }})
                            .build();
                }
                c = restClient;
            }
        }
        return c;
    }
}
