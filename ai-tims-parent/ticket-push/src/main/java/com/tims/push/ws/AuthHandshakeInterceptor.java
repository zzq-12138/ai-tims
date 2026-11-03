package com.tims.push.ws;

import cn.dev33.satoken.stp.StpUtil;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.server.ServerHttpRequest;
import org.springframework.http.server.ServerHttpResponse;
import org.springframework.http.server.ServletServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.socket.WebSocketHandler;
import org.springframework.web.socket.server.HandshakeInterceptor;

import java.util.Map;

/**
 * WS 握手鉴权（M4）：
 * - token 携带方式：连接 URL query 参数 ?token=xxx（浏览器 WebSocket API 无法自定义请求头，
 *   故不走 Authorization 头；token 即登录返回的 Sa-Token 串，会话存 Redis 与其他服务共享）；
 * - 校验方式：StpUtil.getLoginIdByToken(token)（Redis 会话共享校验），
 *   通过后从会话取 tenantId 写入 WS attributes；失败返回 401 拒绝握手。
 */
@Component
public class AuthHandshakeInterceptor implements HandshakeInterceptor {

    private static final Logger log = LoggerFactory.getLogger(AuthHandshakeInterceptor.class);

    @Override
    public boolean beforeHandshake(ServerHttpRequest request, ServerHttpResponse response,
                                   WebSocketHandler wsHandler, Map<String, Object> attributes) {
        if (!(request instanceof ServletServerHttpRequest req)) {
            return false;
        }
        String token = req.getServletRequest().getParameter("token");
        if (token == null || token.isBlank()) {
            log.warn("WS 握手拒绝：缺少 token");
            response.setStatusCode(org.springframework.http.HttpStatus.UNAUTHORIZED);
            return false;
        }
        Object loginId = StpUtil.getLoginIdByToken(token);
        if (loginId == null) {
            log.warn("WS 握手拒绝：token 无效或已过期");
            response.setStatusCode(org.springframework.http.HttpStatus.UNAUTHORIZED);
            return false;
        }
        long userId = Long.parseLong(String.valueOf(loginId));
        long tenantId = 1L;
        try {
            Object v = StpUtil.getSessionByLoginId(userId).get("tenantId");
            if (v instanceof Long l) tenantId = l;
            else if (v instanceof Integer i) tenantId = i.longValue();
        } catch (Exception ignored) {
        }
        attributes.put("userId", userId);
        attributes.put("tenantId", tenantId);
        return true;
    }

    @Override
    public void afterHandshake(ServerHttpRequest request, ServerHttpResponse response,
                               WebSocketHandler wsHandler, Exception exception) {
    }
}
