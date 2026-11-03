package com.tims.ai.rag;

import com.tims.ai.config.AiProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.core.ParameterizedTypeReference;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;
import org.springframework.web.util.UriComponentsBuilder;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 工单服务客户端（只读能力）：详情 / 关键词检索 / 统计概览。
 * 供 RAG（工单上下文）与 @Tool（工单助手）复用。
 */
@Component
public class OrderClient {

    private static final Logger log = LoggerFactory.getLogger(OrderClient.class);

    private final RestTemplate restTemplate;
    private final AiProperties props;

    public OrderClient(RestTemplate downstreamRestTemplate, AiProperties props) {
        this.restTemplate = downstreamRestTemplate;
        this.props = props;
    }

    /** 工单主单（详情接口不校验登录，租户头必须显式带） */
    @SuppressWarnings("unchecked")
    public Map<String, Object> detail(Long tenantId, Long ticketId) {
        try {
            Map<String, Object> resp = restTemplate.exchange(
                    props.getOrderBaseUrl() + "/api/order/ticket/" + ticketId,
                    HttpMethod.GET, tenantEntity(tenantId),
                    new ParameterizedTypeReference<Map<String, Object>>() { }).getBody();
            if (resp == null || resp.get("data") == null) {
                return null;
            }
            Map<String, Object> data = (Map<String, Object>) resp.get("data");
            Object ticket = data.get("ticket");
            return ticket instanceof Map ? (Map<String, Object>) ticket : null;
        } catch (Exception e) {
            log.warn("[order] 详情查询失败 id={}: {}", ticketId, e.getMessage());
            return null;
        }
    }

    /** 关键词分页（需要登录态，Authorization 由 DownstreamHeaderInterceptor 透传） */
    @SuppressWarnings("unchecked")
    public List<Map<String, Object>> search(Long tenantId, String keyword, int size) {
        try {
            String url = UriComponentsBuilder.fromHttpUrl(props.getOrderBaseUrl() + "/api/order/ticket/page")
                    .queryParam("tab", "ALL")
                    .queryParam("keyword", keyword)
                    .queryParam("page", 1)
                    .queryParam("size", size)
                    .build().encode().toUriString();
            Map<String, Object> resp = restTemplate.exchange(url, HttpMethod.GET, tenantEntity(tenantId),
                    new ParameterizedTypeReference<Map<String, Object>>() { }).getBody();
            if (resp == null || !(resp.get("data") instanceof Map<?, ?> data)) {
                return List.of();
            }
            Object records = ((Map<String, Object>) data).get("records");
            if (records instanceof List<?> list) {
                List<Map<String, Object>> out = new ArrayList<>();
                for (Object o : list) {
                    if (o instanceof Map<?, ?> m) {
                        out.add((Map<String, Object>) m);
                    }
                }
                return out;
            }
            return List.of();
        } catch (Exception e) {
            log.warn("[order] 关键词查询失败 kw={}: {}", keyword, e.getMessage());
            return List.of();
        }
    }

    /** 统计概览（§6.3 #18） */
    @SuppressWarnings("unchecked")
    public Map<String, Object> overview(Long tenantId) {
        try {
            Map<String, Object> resp = restTemplate.exchange(
                    props.getOrderBaseUrl() + "/api/order/stat/overview",
                    HttpMethod.GET, tenantEntity(tenantId),
                    new ParameterizedTypeReference<Map<String, Object>>() { }).getBody();
            if (resp == null || resp.get("data") == null) {
                return null;
            }
            return (Map<String, Object>) resp.get("data");
        } catch (Exception e) {
            log.warn("[order] 统计查询失败: {}", e.getMessage());
            return null;
        }
    }

    private HttpEntity<Void> tenantEntity(Long tenantId) {
        HttpHeaders headers = new HttpHeaders();
        headers.set("X-Tenant-Id", String.valueOf(tenantId == null ? 1L : tenantId));
        return new HttpEntity<>(headers);
    }
}
