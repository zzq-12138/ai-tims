package com.tims.knowledge.config;

import org.springframework.amqp.core.Binding;
import org.springframework.amqp.core.BindingBuilder;
import org.springframework.amqp.core.Queue;
import org.springframework.amqp.core.QueueBuilder;
import org.springframework.amqp.core.TopicExchange;
import org.springframework.amqp.support.converter.Jackson2JsonMessageConverter;
import org.springframework.amqp.support.converter.MessageConverter;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * M6 工单关闭事件消费拓扑。
 * 交换器 tims.ticket.event 与 ticket-order 的 EventPublisher 同名同类型（topic/durable），
 * 独立队列 q.kb.extract 绑定 ticket.closed，与 ticket-push 的 q.push.ticket 各自消费一份（互不影响）。
 * 处理异常统一落 q.kb.extract.dead，避免阻塞关单链路。
 */
@Configuration
public class RabbitKbConfig {

    public static final String EXCHANGE = "tims.ticket.event";
    public static final String ROUTING_KEY = "ticket.closed";
    public static final String QUEUE = "q.kb.extract";
    public static final String DEAD_QUEUE = "q.kb.extract.dead";

    @Bean
    public TopicExchange ticketEventExchange() {
        return new TopicExchange(EXCHANGE, true, false);
    }

    @Bean
    public Queue kbExtractQueue() {
        return QueueBuilder.durable(QUEUE)
                .withArgument("x-dead-letter-exchange", "")
                .withArgument("x-dead-letter-routing-key", DEAD_QUEUE)
                .build();
    }

    @Bean
    public Queue kbExtractDeadQueue() {
        return QueueBuilder.durable(DEAD_QUEUE).build();
    }

    @Bean
    public Binding kbExtractBinding() {
        return BindingBuilder.bind(kbExtractQueue()).to(ticketEventExchange()).with(ROUTING_KEY);
    }

    @Bean
    public MessageConverter rabbitMessageConverter() {
        return new Jackson2JsonMessageConverter();
    }
}
