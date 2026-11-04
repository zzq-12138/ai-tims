package com.tims.knowledge.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.knowledge.dto.ExtractResult;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.Map;

/**
 * ticket-ai 内部抽取接口客户端（M6）。
 * 调用失败抛 IllegalStateException，由上层落“待人工补录”，不向上阻塞消息消费。
 */
@Service
public class ExtractAiClient {

    private static final Logger log = LoggerFactory.getLogger(ExtractAiClient.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final RestTemplate restTemplate;
    private final String baseUrl;

    public ExtractAiClient(@Qualifier("internalRestTemplate") RestTemplate restTemplate,
                           @Value("${tims.kb.extract.ai-base-url:http://ticket-ai}") String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = trimSlash(baseUrl);
    }

    public ExtractResult extract(Long tenantId, Map<String, Object> payload) {
        HttpHeaders headers = new HttpHeaders();
        headers.setContentType(MediaType.APPLICATION_JSON);
        headers.set("X-Tenant-Id", String.valueOf(tenantId));
        HttpEntity<Map<String, Object>> entity = new HttpEntity<>(payload, headers);
        String resp = restTemplate.postForObject(baseUrl + "/api/ai/internal/extract", entity, String.class);
        try {
            JsonNode root = MAPPER.readTree(resp == null ? "{}" : resp);
            int code = root.path("code").asInt(-1);
            if (code != 0) {
                throw new IllegalStateException("抽取接口返回失败: code=" + code
                        + " message=" + root.path("message").asText(""));
            }
            JsonNode data = root.get("data");
            if (data == null || data.isNull()) {
                throw new IllegalStateException("抽取接口返回空数据");
            }
            ExtractResult r = new ExtractResult();
            r.setTitle(data.path("title").asText(""));
            r.setDeviceType(data.path("deviceType").asText(""));
            r.setFaultPhenomenon(data.path("faultPhenomenon").asText(""));
            r.setTroubleshootSteps(data.path("troubleshootSteps").asText(""));
            r.setSolutionSteps(data.path("solutionSteps").asText(""));
            r.setKeyPoints(data.path("keyPoints").asText(""));
            r.setModel(data.path("model").asText(""));
            r.setPromptTokens(data.path("promptTokens").asInt(0));
            r.setCompletionTokens(data.path("completionTokens").asInt(0));
            r.setTotalTokens(data.path("totalTokens").asInt(0));
            r.setLatencyMs(data.path("latencyMs").asLong(0));
            if (data.path("tags").isArray()) {
                java.util.List<String> tags = new java.util.ArrayList<>();
                data.path("tags").forEach(n -> tags.add(n.asText()));
                r.setTags(tags);
            }
            return r;
        } catch (IllegalStateException e) {
            throw e;
        } catch (Exception e) {
            log.warn("[extract-ai] 调用失败: {}", e.getMessage());
            throw new IllegalStateException("抽取服务调用失败: " + e.getMessage(), e);
        }
    }

    private static String trimSlash(String s) {
        return s != null && s.endsWith("/") ? s.substring(0, s.length() - 1) : s;
    }
}
