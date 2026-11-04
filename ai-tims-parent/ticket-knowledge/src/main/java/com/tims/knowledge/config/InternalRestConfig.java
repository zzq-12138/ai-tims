package com.tims.knowledge.config;

import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

/**
 * M6 内部调用（lb://ticket-ai 抽取、lb://ticket-order 工单详情/标记）。
 * 抽取为同步 LLM 调用，读超时必须覆盖模型最大耗时（这里 150s），避免消费线程过早失败。
 */
@Configuration
public class InternalRestConfig {

    @Bean
    @LoadBalanced
    public RestTemplate internalRestTemplate() {
        SimpleClientHttpRequestFactory factory = new SimpleClientHttpRequestFactory();
        factory.setConnectTimeout(5_000);
        factory.setReadTimeout(150_000);
        return new RestTemplate(factory);
    }
}
