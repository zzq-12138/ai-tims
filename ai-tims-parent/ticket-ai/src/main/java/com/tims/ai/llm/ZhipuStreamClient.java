package com.tims.ai.llm;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.ai.config.AiProperties;
import java.io.BufferedReader;
import java.io.IOException;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import java.net.http.HttpTimeoutException;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

/**
 * 智谱 GLM SSE 流式客户端（OpenAI 兼容协议）。
 * 直接消费原生 SSE，保留 reasoning_content（思考流）与最终 usage；Spring AI 的 OpenAI 流式映射会丢弃该字段，
 * 因此流式链路用本客户端，Spring AI 负责同步问答与 @Tool 工具调用。
 */
@Component
public class ZhipuStreamClient {

    private static final Logger log = LoggerFactory.getLogger(ZhipuStreamClient.class);

    private final AiProperties props;
    private final ZhipuKeyProvider keyProvider;
    private final ObjectMapper mapper;
    private final HttpClient httpClient = HttpClient.newBuilder()
            .connectTimeout(Duration.ofSeconds(5))
            .build();

    public ZhipuStreamClient(AiProperties props, ZhipuKeyProvider keyProvider, ObjectMapper mapper) {
        this.props = props;
        this.keyProvider = keyProvider;
        this.mapper = mapper;
    }

    /** 流式回调：思考片段与正文片段分开上抛 */
    public interface Listener {
        default void onReasoning(String delta) { }
        default void onContent(String delta) { }
    }

    /** token 用量 */
    public record TokenUsage(long promptTokens, long completionTokens, long totalTokens, long reasoningTokens) {
        public static final TokenUsage EMPTY = new TokenUsage(0, 0, 0, 0);
    }

    /** 流式结果 */
    public record StreamResult(long firstTokenMs, long firstContentMs, long totalMs,
                               int reasoningChars, TokenUsage usage, String finishReason) { }

    /**
     * 发起流式对话。
     *
     * @param model     模型名（glm-4-flash / glm-5.3-flash）
     * @param messages  [{role, content}]
     * @param listener  增量回调
     */
    public StreamResult stream(String model, int maxTokens, double temperature,
                               List<Map<String, String>> messages, Listener listener) {
        String key = keyProvider.getKey();
        if (key.isEmpty()) {
            throw new LlmException(40201, "AI 服务暂不可用：未配置智谱 API Key");
        }
        long t0 = System.currentTimeMillis();
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("model", model);
        body.put("messages", messages);
        body.put("max_tokens", maxTokens);
        body.put("temperature", temperature);
        body.put("stream", true);

        HttpRequest request = HttpRequest.newBuilder(URI.create(props.getBaseUrl() + props.getCompletionsPath()))
                .timeout(Duration.ofMillis(props.getReadTimeoutMs()))
                .header("Authorization", "Bearer " + key)
                .header("Content-Type", "application/json")
                .header("Accept", "text/event-stream")
                .POST(HttpRequest.BodyPublishers.ofString(toJson(body), StandardCharsets.UTF_8))
                .build();

        HttpResponse<InputStream> response;
        try {
            response = httpClient.send(request, HttpResponse.BodyHandlers.ofInputStream());
        } catch (HttpTimeoutException e) {
            throw new LlmException(40202, "AI 服务响应超时（" + props.getReadTimeoutMs() + "ms），请稍后重试");
        } catch (IOException | InterruptedException e) {
            if (e instanceof InterruptedException) {
                Thread.currentThread().interrupt();
            }
            throw new LlmException(40201, "AI 服务不可用：" + e.getMessage());
        }

        if (response.statusCode() != 200) {
            String detail = readQuietly(response.body());
            throw new LlmException(mapStatus(response.statusCode()),
                    "智谱接口返回 " + response.statusCode() + "：" + trim(detail, 200));
        }

        long firstToken = -1;
        long firstContent = -1;
        int reasoningChars = 0;
        TokenUsage usage = TokenUsage.EMPTY;
        String finishReason = null;

        try (BufferedReader reader = new BufferedReader(
                new InputStreamReader(response.body(), StandardCharsets.UTF_8))) {
            String line;
            while ((line = reader.readLine()) != null) {
                line = line.trim();
                if (!line.startsWith("data:")) {
                    continue;
                }
                String payload = line.substring(5).trim();
                if (payload.isEmpty()) {
                    continue;
                }
                if ("[DONE]".equals(payload)) {
                    break;
                }
                JsonNode node;
                try {
                    node = mapper.readTree(payload);
                } catch (Exception ignore) {
                    continue;
                }
                JsonNode err = node.get("error");
                if (err != null) {
                    throw new LlmException(40201, "AI 服务返回错误：" + trim(err.toString(), 200));
                }
                JsonNode usageNode = node.get("usage");
                if (usageNode != null && !usageNode.isNull()) {
                    usage = parseUsage(usageNode);
                }
                JsonNode choices = node.get("choices");
                if (choices == null || !choices.isArray() || choices.isEmpty()) {
                    continue;
                }
                JsonNode choice = choices.get(0);
                if (choice.get("finish_reason") != null && !choice.get("finish_reason").isNull()) {
                    finishReason = choice.get("finish_reason").asText();
                }
                JsonNode delta = choice.get("delta");
                if (delta == null) {
                    continue;
                }
                String reasoning = text(delta.get("reasoning_content"));
                String content = text(delta.get("content"));
                if (reasoning != null && !reasoning.isEmpty()) {
                    if (firstToken < 0) {
                        firstToken = System.currentTimeMillis() - t0;
                    }
                    reasoningChars += reasoning.length();
                    listener.onReasoning(reasoning);
                }
                if (content != null && !content.isEmpty()) {
                    if (firstToken < 0) {
                        firstToken = System.currentTimeMillis() - t0;
                    }
                    if (firstContent < 0) {
                        firstContent = System.currentTimeMillis() - t0;
                    }
                    listener.onContent(content);
                }
            }
        } catch (LlmException e) {
            throw e;
        } catch (IOException e) {
            throw new LlmException(40202, "AI 流式读取中断：" + e.getMessage());
        }

        long total = System.currentTimeMillis() - t0;
        log.info("[llm] stream done model={} firstToken={}ms firstContent={}ms total={}ms usage={}/{}",
                model, firstToken, firstContent, total, usage.promptTokens(), usage.completionTokens());
        return new StreamResult(firstToken, firstContent, total, reasoningChars, usage, finishReason);
    }

    private TokenUsage parseUsage(JsonNode u) {
        long prompt = u.path("prompt_tokens").asLong(0);
        long completion = u.path("completion_tokens").asLong(0);
        long total = u.path("total_tokens").asLong(prompt + completion);
        long reasoning = u.path("completion_tokens_details").path("reasoning_tokens").asLong(0);
        return new TokenUsage(prompt, completion, total, reasoning);
    }

    private String text(JsonNode n) {
        return (n == null || n.isNull()) ? null : n.asText();
    }

    private int mapStatus(int status) {
        if (status == 401 || status == 403) {
            return 40201;
        }
        return 40201;
    }

    private String readQuietly(InputStream in) {
        try (InputStream is = in) {
            return new String(is.readNBytes(2048), StandardCharsets.UTF_8);
        } catch (IOException e) {
            return "";
        }
    }

    private String toJson(Object o) {
        try {
            return mapper.writeValueAsString(o);
        } catch (Exception e) {
            throw new LlmException(40201, "请求序列化失败：" + e.getMessage());
        }
    }

    private static String trim(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }
}
