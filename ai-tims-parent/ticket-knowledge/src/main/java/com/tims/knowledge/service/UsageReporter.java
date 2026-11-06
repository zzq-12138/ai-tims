package com.tims.knowledge.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.MediaType;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestClient;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * embedding 用量回传（M6）：每次 /embeddings 成功后异步上报 ticket-ai 落 ai_call_log。
 * 批量按批记 1 条（scene=EMBED，total_tokens=usage.prompt_tokens）。
 * 上报失败只打 warn 日志，绝不阻断检索/同步业务。
 */
@Component
public class UsageReporter {

    private static final Logger log = LoggerFactory.getLogger(UsageReporter.class);

    @Value("${tims.kb.usage-report.enabled:true}")
    private boolean enabled;

    @Value("${tims.kb.usage-report.url:http://localhost:8104/api/ai/usage/record}")
    private String url;

    @Value("${tims.kb.usage-report.tenant-id:1}")
    private long tenantId;

    /** 守护线程池：不阻塞主流程，也不阻止 JVM 退出 */
    private final ExecutorService pool = Executors.newFixedThreadPool(2, r -> {
        Thread t = new Thread(r, "embed-usage-report");
        t.setDaemon(true);
        return t;
    });

    private volatile RestClient client;

    public void report(String scene, String model, int promptTokens, long latencyMs) {
        if (!enabled || promptTokens <= 0) {
            return;
        }
        try {
            pool.submit(() -> {
                try {
                    Map<String, Object> body = new LinkedHashMap<>();
                    body.put("tenantId", tenantId);
                    body.put("scene", scene);
                    body.put("model", model);
                    body.put("promptTokens", promptTokens);
                    body.put("completionTokens", 0);
                    body.put("latencyMs", latencyMs);
                    ensureClient().post().uri(url)
                            .contentType(MediaType.APPLICATION_JSON)
                            .body(body)
                            .retrieve()
                            .toBodilessEntity();
                } catch (Exception e) {
                    log.warn("[usage] embedding 用量上报失败（不影响检索）: {}", e.getMessage());
                }
            });
        } catch (Exception e) {
            log.warn("[usage] embedding 用量上报提交失败（不影响检索）: {}", e.getMessage());
        }
    }

    private RestClient ensureClient() {
        RestClient c = client;
        if (c == null) {
            synchronized (this) {
                if (client == null) {
                    client = RestClient.builder()
                            .requestFactory(new org.springframework.http.client.SimpleClientHttpRequestFactory() {{
                                setConnectTimeout(2_000);
                                setReadTimeout(3_000);
                            }})
                            .build();
                }
                c = client;
            }
        }
        return c;
    }
}
