package com.tims.ai.fallback;

import com.tims.ai.config.AiProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 建议→回填：把配对记录投递为 ticket-knowledge 的 ai_extracted 待审条目。
 * 只投递，不写 kb_knowledge、不动 Milvus；任何失败只告警，不影响回填结果。
 */
@Component
public class FallbackIntakeClient {

    private static final Logger log = LoggerFactory.getLogger(FallbackIntakeClient.class);

    private final RestTemplate restTemplate;
    private final AiProperties props;

    /** 服务间共享密钥：与 ticket-knowledge 同源（TIMS_INTERNAL_TOKEN）；留空时默认不投递 */
    @Value("${tims.internal-token:}")
    private String internalToken;

    public FallbackIntakeClient(RestTemplate downstreamRestTemplate, AiProperties props) {
        this.restTemplate = downstreamRestTemplate;
        this.props = props;
    }

    /** @return true 表示服务端已接收（含幂等命中） */
    public boolean submit(FallbackPair p, String confidence) {
        if (internalToken == null || internalToken.isBlank()) {
            log.warn("[fallback-intake] 未配置 TIMS_INTERNAL_TOKEN，跳过投递 pair={}", p.getId());
            return false;
        }
        try {
            Map<String, Object> body = new LinkedHashMap<>();
            body.put("tenantId", p.getTenantId());
            body.put("fallbackPairId", String.valueOf(p.getId()));
            body.put("ticketId", p.getTicketId() == null ? null : String.valueOf(p.getTicketId()));
            body.put("ticketNo", p.getTicketNo());
            body.put("ticketTitle", p.getTicketTitle());
            body.put("sessionId", p.getSessionId());
            body.put("model", p.getModel());
            body.put("promptVersion", p.getPromptVersion());
            body.put("confidence", confidence);
            body.put("coverageVerdict", p.getCoverageVerdict());
            body.put("suggestionText", p.getSuggestionText());
            body.put("actualDisposition", p.getActualDisposition());

            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("X-Tenant-Id", String.valueOf(p.getTenantId()));
            headers.set("X-Internal-Token", internalToken);
            HttpEntity<Map<String, Object>> entity = new HttpEntity<>(body, headers);
            Map<?, ?> resp = restTemplate.postForObject(
                    props.getKbBaseUrl() + "/api/kb/extraction/intake/fallback", entity, Map.class);
            Object data = resp == null ? null : resp.get("data");
            boolean accepted = data instanceof Map<?, ?> m && Boolean.TRUE.equals(m.get("accepted"));
            log.info("[fallback-intake] pair={} submitted accepted={}", p.getId(), accepted);
            return accepted;
        } catch (Exception e) {
            log.warn("[fallback-intake] pair={} 投递失败，忽略：{}", p.getId(), e.getMessage());
            return false;
        }
    }
}
