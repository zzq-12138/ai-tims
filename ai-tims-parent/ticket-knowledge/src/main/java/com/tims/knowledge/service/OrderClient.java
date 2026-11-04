package com.tims.knowledge.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.web.client.RestTemplate;

import java.util.ArrayList;
import java.util.List;

/**
 * ticket-order 内部客户端（M6）：拉取已关闭工单详情、标记已 AI 提炼（adoptionRate 数据源）。
 * 直接走 lb://ticket-order 内部接口，不经网关，租户通过 X-Tenant-Id 显式透传。
 */
@Service
public class OrderClient {

    private static final Logger log = LoggerFactory.getLogger(OrderClient.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();

    private final RestTemplate restTemplate;
    private final String baseUrl;

    public OrderClient(@Qualifier("internalRestTemplate") RestTemplate restTemplate,
                       @Value("${tims.kb.extract.order-base-url:http://ticket-order}") String baseUrl) {
        this.restTemplate = restTemplate;
        this.baseUrl = baseUrl != null && baseUrl.endsWith("/") ? baseUrl.substring(0, baseUrl.length() - 1) : baseUrl;
    }

    /** 返回 { ticket:Map, flows:List<String>, comments:List<String> } */
    @SuppressWarnings("unchecked")
    public Detail detail(Long tenantId, Long ticketId) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Tenant-Id", String.valueOf(tenantId));
        HttpEntity<Void> entity = new HttpEntity<>(headers);
        ResponseEntity<String> resp = restTemplate.exchange(
                baseUrl + "/api/order/ticket/" + ticketId, HttpMethod.GET, entity, String.class);
        try {
            JsonNode root = MAPPER.readTree(resp.getBody() == null ? "{}" : resp.getBody());
            if (root.path("code").asInt(-1) != 0) {
                throw new IllegalStateException("工单详情返回失败: " + root.path("message").asText(""));
            }
            JsonNode data = root.path("data");
            JsonNode ticket = data.path("ticket");
            Detail d = new Detail();
            d.title = ticket.path("title").asText("");
            d.description = ticket.path("description").asText("");
            d.resolveNote = ticket.path("resolveNote").asText("");
            d.deviceType = ticket.path("deviceType").asText("");
            d.ticketNo = ticket.path("ticketNo").asText("");
            JsonNode flows = data.path("flows");
            if (flows.isArray()) {
                for (JsonNode f : flows) {
                    String action = f.path("action").asText("");
                    String comment = f.path("comment").asText("");
                    if (!action.isEmpty() || !comment.isEmpty()) {
                        d.flows.add((action + " " + comment).trim());
                    }
                }
            }
            JsonNode comments = data.path("comments");
            if (comments.isArray()) {
                for (JsonNode c : comments) {
                    String content = c.path("content").asText("");
                    if (!content.isEmpty()) {
                        d.comments.add(c.path("userName").asText("") + "：" + content);
                    }
                }
            }
            return d;
        } catch (IllegalStateException e) {
            throw e;
        } catch (Exception e) {
            throw new IllegalStateException("工单详情解析失败: " + e.getMessage(), e);
        }
    }

    /** 标记工单已 AI 提炼（失败仅告警，不影响审核/知识落库） */
    public void markAiExtracted(Long tenantId, Long ticketId) {
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.set("X-Tenant-Id", String.valueOf(tenantId));
            HttpEntity<Void> entity = new HttpEntity<>(headers);
            restTemplate.exchange(baseUrl + "/api/order/ticket/" + ticketId + "/ai-extracted",
                    HttpMethod.POST, entity, String.class);
        } catch (Exception e) {
            log.warn("[order] 标记 ai_extracted 失败 ticket={}: {}", ticketId, e.getMessage());
        }
    }

    public static class Detail {
        public String title;
        public String description;
        public String resolveNote;
        public String deviceType;
        public String ticketNo;
        public List<String> flows = new ArrayList<>();
        public List<String> comments = new ArrayList<>();
    }
}
