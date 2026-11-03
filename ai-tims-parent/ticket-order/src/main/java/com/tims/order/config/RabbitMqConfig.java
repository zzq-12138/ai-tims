package com.tims.order.config;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.rabbit.connection.ConnectionFactory;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.cloud.client.loadbalancer.LoadBalanced;
import org.springframework.web.client.RestTemplate;

/**
 * RabbitMQ 拓扑与基础设施（M4）。
 *
 * 拓扑（消费侧队列由 ticket-push 声明，此处声明交换机 + 死信侧，双方幂等声明）：
 *   tims.ticket.event (topic) --routing key: ticket.created / ticket.closed--> q.push.ticket（push 声明，含 DLX 参数）
 *   tims.ticket.dlx    (topic) --ticket.#--> q.push.ticket.dead（死信队列：消费失败重试耗尽后落此排查/重放）
 * 消息体统一 JSON（EventPublisher 序列化后的字符串走 Jackson2JsonMessageConverter 透传）。
 */
@Configuration
public class RabbitMqConfig {

    public static final String EVENT_EXCHANGE = "tims.ticket.event";
    public static final String DLX_EXCHANGE = "tims.ticket.dlx";
    public static final String DLQ_QUEUE = "q.push.ticket.dead";

    @Bean
    public TopicExchange ticketEventExchange() {
        return new TopicExchange(EVENT_EXCHANGE, true, false);
    }

    @Bean
    public TopicExchange ticketDlxExchange() {
        return new TopicExchange(DLX_EXCHANGE, true, false);
    }

    @Bean
    public Queue ticketDeadLetterQueue() {
        return QueueBuilder.durable(DLQ_QUEUE).build();
    }

    @Bean
    public Binding dlqBinding() {
        return BindingBuilder.bind(ticketDeadLetterQueue()).to(ticketDlxExchange()).with("ticket.#");
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
        template.setMandatory(true);
        return template;
    }

    /** 服务间 lb 调用（MQ 降级 HTTP 直调 ticket-push 用），支持 http://ticket-push 服务名寻址 */
    @Bean
    @LoadBalanced
    public RestTemplate lbRestTemplate() {
        return new RestTemplate();
    }
}
