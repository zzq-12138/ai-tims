package com.tims.order.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.amqp.AmqpException;
import org.springframework.amqp.rabbit.core.RabbitTemplate;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.http.HttpEntity;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.stereotype.Service;
import org.springframework.transaction.support.TransactionSynchronization;
import org.springframework.transaction.support.TransactionSynchronizationManager;
import org.springframework.web.client.RestTemplate;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

/**
 * 领域事件发布（M4：Redis 桩升级为 RabbitMQ，任务书 §4.4）。
 *
 * 链路：事务提交后 → Topic 交换机 tims.ticket.event（routing key = 事件名，如 ticket.created）。
 * 降级矩阵（发送失败时逐级兜底，绝不静默丢事件）：
 *   ① MQ 发送异常 → HTTP 直调 ticket-push /api/push/internal/event（其用本地线程池同步处理，降级位+2）；
 *   ② HTTP 也失败 → 写 Redis List tims:event:stream（push 服务兜底扫描器消费，降级位+2）。
 * t_event_sent 语义：事件离开 order 服务的时间（MQ send 返回 / HTTP 返回）。
 */
@Service
public class EventPublisher {

    private static final Logger log = LoggerFactory.getLogger(EventPublisher.class);

    /** 与 ticket-push RabbitMqConfig 对齐：Topic 交换机，routing key = ticket.created / ticket.closed */
    public static final String EVENT_EXCHANGE = "tims.ticket.event";
    /** 双重失败兜底：Redis 事件流（push 定时扫描） */
    public static final String FALLBACK_STREAM_KEY = "tims:event:stream";

    private final RabbitTemplate rabbitTemplate;
    private final StringRedisTemplate redis;
    private final RestTemplate lbRestTemplate;
    private final ObjectMapper objectMapper = new ObjectMapper();

    /** 内部降级接口共享密钥（重启脚本注入，不进 git） */
    @Value("${tims.internal-token:tims-internal-dev}")
    private String internalToken;

    public EventPublisher(RabbitTemplate rabbitTemplate,
                          StringRedisTemplate redis,
                          RestTemplate lbRestTemplate) {
        this.rabbitTemplate = rabbitTemplate;
        this.redis = redis;
        this.lbRestTemplate = lbRestTemplate;
    }

    /**
     * 发布领域事件。业务代码在事务内调用，实际发送延迟到事务提交后（避免发出已回滚的事件）。
     * 事件体在 payload 基础上补 eventType / tCreated / tEventSent / occurredAt。
     *
     * @param eventType 事件名 = routing key（ticket.created / ticket.closed）
     * @param payload   事件负载（tenantId/ticketId/ticketNo/deviceType/title/description/handlerId/tCreated）
     */
    public void publish(String eventType, Map<String, Object> payload) {
        if (TransactionSynchronizationManager.isSynchronizationActive()) {
            TransactionSynchronizationManager.registerSynchronization(new TransactionSynchronization() {
                @Override
                public void afterCommit() {
                    doPublish(eventType, payload);
                }
            });
        } else {
            doPublish(eventType, payload);
        }
    }

    private void doPublish(String eventType, Map<String, Object> payload) {
        Map<String, Object> event = new HashMap<>(payload);
        event.put("eventType", eventType);
        event.put("tCreated", String.valueOf(
                payload.getOrDefault("tCreated", LocalDateTime.now())));
        String json;
        try {
            json = objectMapper.writeValueAsString(event);
        } catch (Exception e) {
            json = String.valueOf(event);
        }

        // ① RabbitMQ（Jackson2JsonMessageConverter 序列化为 JSON 对象体，消费侧对称反序列化）
        try {
            event.put("tEventSent", LocalDateTime.now().toString());
            rabbitTemplate.convertAndSend(EVENT_EXCHANGE, eventType, event, m -> {
                m.getMessageProperties().setMessageId(eventType + "-"
                        + event.getOrDefault("ticketId", "0"));
                m.getMessageProperties().setHeader("eventType", eventType);
                return m;
            });
            log.info("[事件发布-MQ] {} ticketId={}", eventType, event.get("ticketId"));
            return;
        } catch (AmqpException e) {
            log.warn("[事件发布] MQ 不可用，降级 HTTP 直调 push：{} - {}", eventType, e.getMessage());
        }

        // ② HTTP 直调 ticket-push（降级矩阵：本地线程池直连）
        try {
            HttpHeaders headers = new HttpHeaders();
            headers.setContentType(MediaType.APPLICATION_JSON);
            headers.set("X-Internal-Token", internalToken);
            ResponseEntity<String> resp = lbRestTemplate.postForEntity(
                    "http://ticket-push/api/push/internal/event",
                    new HttpEntity<>(json, headers), String.class);
            if (resp.getStatusCode().is2xxSuccessful()) {
                log.info("[事件发布-HTTP降级] {} ticketId={}", eventType, event.get("ticketId"));
                return;
            }
            log.warn("[事件发布] HTTP 降级返回异常状态 {}：{}", resp.getStatusCode(), resp.getBody());
        } catch (Exception e) {
            log.warn("[事件发布] HTTP 降级失败：{} - {}", eventType, e.getMessage());
        }

        // ③ Redis 兜底流（push 扫描器消费）
        try {
            event.put("tEventSent", LocalDateTime.now().toString());
            redis.opsForList().leftPush(FALLBACK_STREAM_KEY,
                    objectMapper.writeValueAsString(event));
            log.error("[事件发布-Redis兜底] {} ticketId={}，等待 push 扫描器消费", eventType, event.get("ticketId"));
        } catch (Exception e) {
            log.error("[事件发布] 三级全部失败，事件丢失！{} payload={}", eventType, event, e);
        }
    }
}
