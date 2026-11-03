package com.tims.order.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.Map;

/**
 * 事件发布（任务书 §4.4 ticket.closed 等）。
 * M2 stub：日志 + Redis List tims:event:stream（保留最近 1000 条，便于联调观测）；
 * M4 换 RabbitMQ 广播，接口签名不变。
 */
@Service
public class EventPublisher {

    private static final Logger log = LoggerFactory.getLogger(EventPublisher.class);

    public static final String EVENT_STREAM_KEY = "tims:event:stream";
    private static final long STREAM_MAX_LEN = 1000;

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public EventPublisher(StringRedisTemplate redis) {
        this.redis = redis;
    }

    /**
     * 发布领域事件。
     *
     * @param eventType 事件名（如 ticket.closed）
     * @param payload   事件负载（ticketId/ticketNo/handler 等）
     */
    public void publish(String eventType, Map<String, Object> payload) {
        Map<String, Object> event = new HashMap<>(payload);
        event.put("eventType", eventType);
        event.put("occurredAt", LocalDateTime.now().toString());
        String json;
        try {
            json = objectMapper.writeValueAsString(event);
        } catch (Exception e) {
            json = String.valueOf(event);
        }
        log.info("[事件发布] {} {}", eventType, json);
        redis.opsForList().leftPush(EVENT_STREAM_KEY, json);
        redis.opsForList().trim(EVENT_STREAM_KEY, 0, STREAM_MAX_LEN - 1);
    }
}
