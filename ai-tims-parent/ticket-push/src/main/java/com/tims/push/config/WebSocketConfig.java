package com.tims.push.config;

import com.tims.push.ws.AuthHandshakeInterceptor;
import com.tims.push.ws.PushWebSocketHandler;
import org.springframework.context.annotation.Configuration;
import org.springframework.web.socket.config.annotation.EnableWebSocket;
import org.springframework.web.socket.config.annotation.WebSocketConfigurer;
import org.springframework.web.socket.config.annotation.WebSocketHandlerRegistry;

/**
 * WS 端点注册（M4）：/ws/push，网关路由 /ws/** → lb:ws://ticket-push 原样转发。
 * token 经 query 参数 ?token=xxx 携带，AuthHandshakeInterceptor 用 Sa-Token 校验。
 */
@Configuration
@EnableWebSocket
public class WebSocketConfig implements WebSocketConfigurer {

    private final PushWebSocketHandler pushWebSocketHandler;
    private final AuthHandshakeInterceptor authHandshakeInterceptor;

    public WebSocketConfig(PushWebSocketHandler pushWebSocketHandler,
                           AuthHandshakeInterceptor authHandshakeInterceptor) {
        this.pushWebSocketHandler = pushWebSocketHandler;
        this.authHandshakeInterceptor = authHandshakeInterceptor;
    }

    @Override
    public void registerWebSocketHandlers(WebSocketHandlerRegistry registry) {
        registry.addHandler(pushWebSocketHandler, "/ws/push")
                .addInterceptors(authHandshakeInterceptor)
                .setAllowedOriginPatterns("*");
    }
}
