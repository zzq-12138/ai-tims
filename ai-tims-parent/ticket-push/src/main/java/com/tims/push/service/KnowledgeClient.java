package com.tims.push.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.net.URLEncoder;
import java.nio.charset.StandardCharsets;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 知识检索客户端（M4）：推送服务调 kb 服务 HYBRID 检索。
 * kb 自身不做服务内鉴权（网关统一鉴权），服务间直调携带 X-Tenant-Id（kb TenantContext 兜底读取）。
 * 返回统一封装：available=false 表示 kb 调用失败（推送管线据此推空卡片 + 明确提示）；
 * fallback 透传 kb 返回体（Milvus 不可用降级纯关键词时为 true）。
 */
@Service
public class KnowledgeClient {

    private static final Logger log = LoggerFactory.getLogger(KnowledgeClient.class);

    private final RestTemplate kbRestTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    @Value("${tims.push.kb-base-url:http://ticket-knowledge}")
    private String kbBaseUrl;

    public KnowledgeClient(RestTemplate kbRestTemplate) {
        this.kbRestTemplate = kbRestTemplate;
    }

    /** HYBRID 检索；kb 不可用抛出由调用方捕获（返回体 available=false） */
    @SuppressWarnings("unchecked")
    public KbResult searchHybrid(Long tenantId, String query, int topK) {
        String url = kbBaseUrl + "/api/kb/search?query="
                + URLEncoder.encode(query, StandardCharsets.UTF_8)
                + "&mode=HYBRID&topK=" + topK;
        try {
            Map<String, Object> resp = kbRestTemplate.getForEntity(url, Map.class).getBody();
            Map<String, Object> body = resp == null ? Map.of() : resp;
            if (!Integer.valueOf(0).equals(((Number) body.getOrDefault("code", -1)).intValue())) {
                throw new IllegalStateException("kb 返回业务码异常：" + body.get("code"));
            }
            Map<String, Object> data = (Map<String, Object>) body.getOrDefault("data", Map.of());
            List<Map<String, Object>> items = (List<Map<String, Object>>) data.getOrDefault("items", List.of());
            boolean fallback = Boolean.TRUE.equals(data.get("fallback"));
            return new KbResult(true, fallback, items);
        } catch (Exception e) {
            log.warn("kb 检索调用失败 query={}：{}", query, e.getMessage());
            return new KbResult(false, true, List.of());
        }
    }

    /** 检索结果封装 */
    public record KbResult(boolean available, boolean fallback, List<Map<String, Object>> items) {
    }
}
