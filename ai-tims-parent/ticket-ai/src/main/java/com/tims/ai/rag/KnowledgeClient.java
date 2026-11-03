package com.tims.ai.rag;

import com.tims.ai.config.AiProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 知识库检索客户端：调用 ticket-knowledge 的三模式检索（HYBRID + RRF + Milvus 降级）。
 * 不复制检索逻辑，保持 M3 已验收行为不变；本服务只消费。
 */
@Component
public class KnowledgeClient {

    private static final Logger log = LoggerFactory.getLogger(KnowledgeClient.class);

    private final RestTemplate restTemplate;
    private final AiProperties props;

    public KnowledgeClient(RestTemplate downstreamRestTemplate, AiProperties props) {
        this.restTemplate = downstreamRestTemplate;
        this.props = props;
    }

    /** 检索结果 */
    public record SearchOutcome(List<KbRef> refs, List<String> contents, String mode,
                                boolean fallback, boolean unavailable, long elapsedMs) {
        public static SearchOutcome unavailable(long elapsedMs) {
            return new SearchOutcome(List.of(), List.of(), "KEYWORD", true, true, elapsedMs);
        }
    }

    /**
     * HYBRID 检索 TopK，返回引用与截断后的正文（供 prompt 拼装）。
     * Milvus 不可用或被降级时 fallback=true；KB 服务整体不可用时 unavailable=true。
     */
    public SearchOutcome search(Long tenantId, String query, int topK) {
        long t0 = System.currentTimeMillis();
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("query", query);
            body.put("mode", "HYBRID");
            body.put("topK", topK);

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("X-Tenant-Id", String.valueOf(tenantId));
            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);

            Map<String, Object> resp = restTemplate.exchange(
                    props.getKbBaseUrl() + "/api/kb/search", HttpMethod.POST, entity,
                    new ParameterizedTypeReference<Map<String, Object>>() { }).getBody();
            long elapsed = System.currentTimeMillis() - t0;
            if (resp == null || resp.get("data") == null) {
                log.warn("[rag] 知识库返回空响应，按降级处理");
                return SearchOutcome.unavailable(elapsed);
            }
            @SuppressWarnings("unchecked")
            Map<String, Object> data = (Map<String, Object>) resp.get("data");
            boolean fallback = Boolean.TRUE.equals(data.get("fallback"));
            List<KbRef> refs = new ArrayList<>();
            List<String> contents = new ArrayList<>();
            Object itemsObj = data.get("items");
            if (itemsObj instanceof List<?> items) {
                for (Object o : items) {
                    if (!(o instanceof Map<?, ?> m)) {
                        continue;
                    }
                    KbRef ref = new KbRef(
                            asLong(m.get("id")),
                            asString(m.get("title")),
                            asString(m.get("summary")),
                            asString(m.get("applyDeviceType")),
                            asLong(m.get("categoryId")),
                            asDouble(m.get("score")));
                    refs.add(ref);
                    String content = asString(m.get("content"));
                    contents.add(snippet(content, props.getSnippetChars()));
                }
            }
            log.info("[rag] kb search ok q='{}' refs={} fallback={} elapsed={}ms",
                    query, refs.size(), fallback, elapsed);
            return new SearchOutcome(refs, contents, String.valueOf(data.getOrDefault("mode", "HYBRID")),
                    fallback, false, elapsed);
        } catch (Exception e) {
            long elapsed = System.currentTimeMillis() - t0;
            log.warn("[rag] 知识库检索失败，降级为无知识上下文: {}", e.getMessage());
            return SearchOutcome.unavailable(elapsed);
        }
    }

    private static String snippet(String s, int max) {
        if (!StringUtils.hasText(s)) {
            return "";
        }
        String oneLine = s.replaceAll("\\s+", " ").trim();
        return oneLine.length() <= max ? oneLine : oneLine.substring(0, max) + "...";
    }

    private static String asString(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static Long asLong(Object o) {
        if (o instanceof Number n) {
            return n.longValue();
        }
        return null;
    }

    private static Double asDouble(Object o) {
        if (o instanceof Number n) {
            return n.doubleValue();
        }
        return null;
    }
}
