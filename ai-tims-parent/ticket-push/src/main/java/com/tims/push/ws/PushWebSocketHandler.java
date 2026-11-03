package com.tims.push.ws;

import com.fasterxml.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.CloseStatus;
import org.springframework.web.socket.TextMessage;
import org.springframework.web.socket.WebSocketSession;
import org.springframework.web.socket.handler.TextWebSocketHandler;

import java.util.List;
import java.util.Map;

/**
 * WS 处理器（/ws/push，网关 lb:ws://ticket-push 路由）：
 * - 建立连接：注册会话 + 写在线表 + 补推未读站内消息（离线期间错过的知识卡片）；
 * - 心跳：客户端每 10s 发 {"type":"PING"}，服务端续期在线表并回 {"type":"PONG"}；
 * - 服务端下行帧：CARD（实时知识卡片）/ UNREAD_CARD（补推）/ PONG。
 */
@Component
public class PushWebSocketHandler extends TextWebSocketHandler {

    private static final Logger log = LoggerFactory.getLogger(PushWebSocketHandler.class);

    private final WsSessionRegistry registry;
    private final com.tims.push.service.MessageService messageService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public PushWebSocketHandler(WsSessionRegistry registry,
                                com.tims.push.service.MessageService messageService) {
        this.registry = registry;
        this.messageService = messageService;
    }

    @Override
    public void afterConnectionEstablished(WebSocketSession session) {
        long userId = (long) session.getAttributes().get("userId");
        long tenantId = (long) session.getAttributes().get("tenantId");
        registry.online(userId, tenantId, session);
        log.info("WS 上线 userId={} tenantId={} 在线数={}", userId, tenantId, registry.listOnline().size());
        // 上线补推：离线期间落库的站内消息
        List<Map<String, Object>> unread = messageService.takeUnreadForPush(userId, tenantId);
        for (Map<String, Object> m : unread) {
            registry.sendToUser(userId, toJson(Map.of("type", "UNREAD_CARD", "data", m)));
        }
        if (!unread.isEmpty()) {
            log.info("上线补推完成 userId={} 条数={}", userId, unread.size());
        }
    }

    @Override
    protected void handleTextMessage(WebSocketSession session, TextMessage message) {
        long userId = (long) session.getAttributes().get("userId");
        long tenantId = (long) session.getAttributes().get("tenantId");
        registry.heartbeat(userId, tenantId); // 任意帧均续期
        String body = message.getPayload();
        if (body.contains("PING")) {
            registry.sendToUser(userId, "{\"type\":\"PONG\",\"ts\":" + System.currentTimeMillis() + "}");
        }
    }

    @Override
    public void afterConnectionClosed(WebSocketSession session, CloseStatus status) {
        Object uid = session.getAttributes().get("userId");
        if (uid != null) {
            long userId = (long) uid;
            registry.offline(userId);
            log.info("WS 下线 userId={} status={}", userId, status);
        }
    }

    private String toJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            return "{}";
        }
    }
}
