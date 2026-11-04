package com.tims.knowledge.consumer;

import com.tims.knowledge.service.ExtractionService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.rabbit.annotation.RabbitListener;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * M6 ticket.closed 消费者（归属 ticket-knowledge：知识落库/审核/合并/向量同步均在本服务，
 * LLM 能力由 ticket-ai 以内部接口提供，职责边界清晰）。
 * 队列 q.kb.extract 与 ticket-push 的 q.push.ticket 各收一份，不互斥。
 */
@Component
public class TicketClosedConsumer {

    private static final Logger log = LoggerFactory.getLogger(TicketClosedConsumer.class);

    private final ExtractionService extractionService;

    public TicketClosedConsumer(ExtractionService extractionService) {
        this.extractionService = extractionService;
    }

    @RabbitListener(queues = "q.kb.extract")
    public void onMessage(Map<String, Object> event) {
        if (event == null) {
            return;
        }
        String type = event.get("eventType") == null ? "" : String.valueOf(event.get("eventType"));
        if (!type.isEmpty() && !"ticket.closed".equals(type)) {
            log.debug("[m6] 非 ticket.closed 事件忽略: {}", type);
            return;
        }
        Long tenantId = event.get("tenantId") instanceof Number n ? n.longValue() : 1L;
        log.info("[m6] 收到 ticket.closed: ticketId={} tenantId={}", event.get("ticketId"), tenantId);
        extractionService.handleClosedEvent(event, tenantId);
    }
}
