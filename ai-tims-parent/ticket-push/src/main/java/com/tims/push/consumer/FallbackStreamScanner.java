package com.tims.push.consumer;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.push.service.PushPipeline;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * Redis 兜底扫描器（M4 降级矩阵第③级自愈）：
 * order 侧 MQ 与 HTTP 双失败时事件落 Redis List tims:event:stream，
 * 本扫描器每 10s 右弹出栈消费（弹出即消费，处理失败重新塞回队尾防丢）。
 * 正常链路（MQ 成功）不写该流，无双消费风险。
 */
@Component
public class FallbackStreamScanner {

    private static final Logger log = LoggerFactory.getLogger(FallbackStreamScanner.class);

    /** 与 order EventPublisher.FALLBACK_STREAM_KEY 对齐（跨模块常量本地镜像，避免依赖 order 包） */
    public static final String FALLBACK_STREAM_KEY = "tims:event:stream";

    private final StringRedisTemplate redis;
    private final PushPipeline pipeline;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public FallbackStreamScanner(StringRedisTemplate redis, PushPipeline pipeline) {
        this.redis = redis;
        this.pipeline = pipeline;
    }

    @Scheduled(fixedDelay = 10_000)
    public void scan() {
        try {
            Object raw;
            while ((raw = redis.opsForList().rightPop(FALLBACK_STREAM_KEY)) != null) {
                try {
                    Map<String, Object> event = objectMapper.readValue(
                            String.valueOf(raw), Map.class);
                    log.warn("[Redis兜底消费] {} ticketId={}",
                            event.get("eventType"), event.get("ticketId"));
                    pipeline.handleEvent(event, true);
                } catch (Exception e) {
                    log.error("[Redis兜底] 处理失败，回退队尾防丢：{}", e.getMessage());
                    redis.opsForList().leftPush(FALLBACK_STREAM_KEY, String.valueOf(raw));
                    break; // 防毒丸消息空转
                }
            }
        } catch (Exception ignored) {
            // Redis 抖动，下个周期重试
        }
    }
}
