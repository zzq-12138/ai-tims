package com.tims.push.consumer;

import com.tims.push.service.PushPipeline;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * MQ 事件消费者（M4）：q.push.ticket ← tims.ticket.event (ticket.#)。
 * 并发 4-8 消费；本地重试 3 次失败 → 不重回队列 → 落死信 q.push.ticket.dead（可排查重放）。
 * 消息体为 JSON 对象（order 侧 Jackson2JsonMessageConverter 对称序列化）。
 */
@Component
public class TicketEventConsumer {

    private static final Logger log = LoggerFactory.getLogger(TicketEventConsumer.class);

    private final PushPipeline pipeline;

    public TicketEventConsumer(PushPipeline pipeline) {
        this.pipeline = pipeline;
    }

    @RabbitListener(queues = "q.push.ticket")
    public void onMessage(Map<String, Object> event) {
        String type = String.valueOf(event.getOrDefault("eventType", "?"));
        long start = System.nanoTime();
        try {
            pipeline.handleEvent(event, false);
            log.info("[MQ消费] {} ticketId={} 耗时 {}ms",
                    type, event.get("ticketId"), (System.nanoTime() - start) / 1_000_000);
        } catch (Exception e) {
            log.error("[MQ消费失败，将重试后落死信] {} ticketId={}", type, event.get("ticketId"), e);
            throw e; // 触发重试/死信（default-requeue-rejected=false）
        }
    }
}
