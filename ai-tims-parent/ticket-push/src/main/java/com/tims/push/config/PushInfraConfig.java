package com.tims.push.config;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.http.client.SimpleClientHttpRequestFactory;
import org.springframework.web.client.RestTemplate;

import java.util.concurrent.ExecutorService;
import java.util.concurrent.LinkedBlockingQueue;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;

/**
 * 推送服务基础设施（M4）。
 *
 * MQ 拓扑（与 order RabbitMqConfig 幂等对齐）：
 *   q.push.ticket  ← tims.ticket.event (topic, ticket.#)，队列参数 x-dead-letter-exchange=tims.ticket.dlx
 *   q.push.ticket.dead ← tims.ticket.dlx (ticket.#)：消费重试 3 次仍失败落死信，可排查/重放
 * 降级矩阵：MQ 不可用 → order HTTP 直调 /api/push/internal/event → 本地线程池执行同一管线。
 */
@Configuration
public class PushInfraConfig {

    public static final String EVENT_EXCHANGE = "tims.ticket.event";
    public static final String PUSH_QUEUE = "q.push.ticket";
    public static final String DLX_EXCHANGE = "tims.ticket.dlx";
    public static final String DLQ_QUEUE = "q.push.ticket.dead";

    @Value("${tims.internal-token:tims-internal-dev}")
    private String internalToken;

    @Value("${tims.push.online-ttl-seconds:30}")
    public int onlineTtlSeconds;

    /** 本地线程池：MQ 不可用降级时由 HTTP 入口直接驱动推送管线 */
    @Bean("pushExecutor")
    public ExecutorService pushExecutor() {
        return new ThreadPoolExecutor(
                4, 16, 60, TimeUnit.SECONDS,
                new LinkedBlockingQueue<>(2000),
                r -> {
                    Thread t = new Thread(r, "push-degrade-" + POOL_SEQ.getAndIncrement());
                    t.setDaemon(true);
                    return t;
                },
                new ThreadPoolExecutor.CallerRunsPolicy());
    }

    private static final java.util.concurrent.atomic.AtomicInteger POOL_SEQ =
            new java.util.concurrent.atomic.AtomicInteger();

    @Bean
    public TopicExchange ticketEventExchange() {
        return new TopicExchange(EVENT_EXCHANGE, true, false);
    }

    @Bean
    public TopicExchange ticketDlxExchange() {
        return new TopicExchange(DLX_EXCHANGE, true, false);
    }

    /** 消费队列：绑定 ticket.#，带死信参数；消费失败重试耗尽 → q.push.ticket.dead */
    @Bean
    public Queue pushQueue() {
        return QueueBuilder.durable(PUSH_QUEUE)
                .deadLetterExchange(DLX_EXCHANGE)
                .deadLetterRoutingKey("ticket.dead")
                .build();
    }

    @Bean
    public Binding pushQueueBinding() {
        return BindingBuilder.bind(pushQueue()).to(ticketEventExchange()).with("ticket.#");
    }

    @Bean
    public Queue deadLetterQueue() {
        return QueueBuilder.durable(DLQ_QUEUE).build();
    }

    @Bean
    public Binding dlqBinding() {
        return BindingBuilder.bind(deadLetterQueue()).to(ticketDlxExchange()).with("ticket.#");
    }

    @Bean
    public MessageConverter jacksonMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }

    @Bean
    public RabbitTemplate rabbitTemplate(ConnectionFactory connectionFactory,
                                         MessageConverter jacksonMessageConverter) {
        RabbitTemplate template = new RabbitTemplate(connectionFactory);
        template.setMessageConverter(jacksonMessageConverter);
        return template;
    }

    /** kb 检索调用（lb 服务名寻址；connect 500ms / read 2500ms 保护 P95 预算） */
    @Bean
    @LoadBalanced
    public RestTemplate kbRestTemplate() {
        SimpleClientHttpRequestFactory f = new SimpleClientHttpRequestFactory();
        f.setConnectTimeout(500);
        f.setReadTimeout(2500);
        return new RestTemplate(f);
    }

    public String internalToken() {
        return internalToken;
    }
}
