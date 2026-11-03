package com.tims.ai.config;

import com.tims.ai.llm.ZhipuKeyProvider;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.ai.openai.api.OpenAiApi;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestTemplate;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * M5 AI 基础设施：Spring AI 接智谱 GLM（OpenAI 兼容端点）、下游 lb 调用、SSE 工作线程池。
 */
@Configuration
public class AiConfig {

    /** Spring AI ChatModel：模型/上限/温度全部来自 AiProperties，切换只改环境变量 */
    @Bean
    public OpenAiChatModel openAiChatModel(AiProperties props, ZhipuKeyProvider keyProvider) {
        String key = keyProvider.getKey();
        if (key.isEmpty()) {
            key = "missing-key";
        }
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(props.getConnectTimeoutMs());
        factory.setReadTimeout((int) props.getReadTimeoutMs());

        OpenAiApi api = OpenAiApi.builder()
                .baseUrl(props.getBaseUrl())
                .apiKey(key)
                .completionsPath(props.getCompletionsPath())
                .restClientBuilder(RestClient.builder().requestFactory(factory))
                .build();

        OpenAiChatOptions options = OpenAiChatOptions.builder()
                .model(props.getModel())
                .maxTokens(props.getMaxTokens())
                .temperature(props.getTemperature())
                .build();

        return OpenAiChatModel.builder()
                .openAiApi(api)
                .defaultOptions(options)
                .build();
    }

    @Bean
    public ChatClient chatClient(OpenAiChatModel model) {
        return ChatClient.builder(model).build();
    }

    /** 跨服务调用（lb://ticket-knowledge、lb://ticket-order），自动透传租户与登录态 */
    @Bean
    @LoadBalanced
    public RestTemplate downstreamRestTemplate(AiProperties props, DownstreamHeaderInterceptor interceptor) {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(props.getConnectTimeoutMs());
        factory.setReadTimeout(30_000);
        RestTemplate rt = new RestTemplate(factory);
        rt.getInterceptors().add(interceptor);
        return rt;
    }

    /** SSE 流式工作线程池：小幅固定容量，避免长连接打满 Tomcat 线程 */
    @Bean(destroyMethod = "shutdown")
    public ExecutorService aiExecutor() {
        AtomicInteger seq = new AtomicInteger(1);
        return Executors.newFixedThreadPool(6, r -> {
            Thread t = new Thread(r, "ai-sse-" + seq.getAndIncrement());
            t.setDaemon(true);
            return t;
        });
    }
}
