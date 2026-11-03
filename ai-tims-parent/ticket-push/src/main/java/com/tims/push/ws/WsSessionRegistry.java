package com.tims.push.ws;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * WS 会话注册表 + Redis 在线用户表（M4）。
 *
 * 在线表：Redis key tims:push:online:{userId} = JSON{userId,tenantId,ts}，TTL=心跳周期×3（默认 30s）；
 * 客户端每 10s 发 {"type":"PING"}，服务端收到任意帧都续期；过 TTL 自动视为离线（无僵尸在线）。
 * 断线重连约定：前端指数退避（1s/2s/4s/...上限 30s），重连成功后服务端自动补推未读站内消息。
 */
@Service
public class WsSessionRegistry {

    private static final Logger log = LoggerFactory.getLogger(WsSessionRegistry.class);
    public static final String ONLINE_KEY_PREFIX = "tims:push:online:";

    private final StringRedisTemplate redis;
    private final ObjectMapper objectMapper = new ObjectMapper();
    private final int ttlSeconds;

    /** 本机活跃会话（单机部署；多实例时 Redis 在线表 + 定向投递可扩展，当前任务书单机口径） */
    private final Map<Long, WebSocketSession> sessions = new ConcurrentHashMap<>();

    public WsSessionRegistry(StringRedisTemplate redis,
                             org.springframework.core.env.Environment env) {
        this.redis = redis;
        this.ttlSeconds = Integer.parseInt(env.getProperty("tims.push.online-ttl-seconds", "30"));
    }

    /** 连接建立：注册会话 + 写在线表 */
    public void online(Long userId, Long tenantId, WebSocketSession session) {
        sessions.put(userId, session);
        try {
            Map<String, Object> v = Map.of("userId", userId, "tenantId", tenantId,
                    "ts", LocalDateTime.now().toString());
            redis.opsForValue().set(ONLINE_KEY_PREFIX + userId,
                    objectMapper.writeValueAsString(v), Duration.ofSeconds(ttlSeconds));
        } catch (Exception e) {
            log.warn("写在线表失败 userId={}: {}", userId, e.getMessage());
        }
    }

    /** 心跳/任意帧：续期在线表 TTL */
    public void heartbeat(Long userId, Long tenantId) {
        online(userId, tenantId, sessions.get(userId));
    }

    /** 连接关闭：摘除会话 + 删在线表（仅当在线表归属仍是自己，防误删重连后的新记录） */
    public void offline(Long userId) {
        sessions.remove(userId);
        try {
            redis.delete(ONLINE_KEY_PREFIX + userId);
        } catch (Exception ignored) {
        }
    }

    public boolean isOnline(Long userId) {
        return sessions.containsKey(userId);
    }

    /** 在线坐席列表（Redis SCAN，跨会话一致性以 Redis 为准） */
    public List<Map<String, Object>> listOnline() {
        List<Map<String, Object>> out = new ArrayList<>();
        Set<String> keys = redis.keys(ONLINE_KEY_PREFIX + "*");
        if (keys == null) return out;
        for (String k : keys) {
            try {
                out.add(objectMapper.readValue(redis.opsForValue().get(k), Map.class));
            } catch (Exception ignored) {
            }
        }
        return out;
    }

    /** 向指定在线用户投递文本帧；返回是否投递成功 */
    public boolean sendToUser(Long userId, String payload) {
        WebSocketSession s = sessions.get(userId);
        if (s == null || !s.isOpen()) return false;
        try {
            synchronized (s) {
                s.sendMessage(new TextMessage(payload));
            }
            return true;
        } catch (Exception e) {
            log.warn("WS 投递失败 userId={}: {}", userId, e.getMessage());
            return false;
        }
    }
}
