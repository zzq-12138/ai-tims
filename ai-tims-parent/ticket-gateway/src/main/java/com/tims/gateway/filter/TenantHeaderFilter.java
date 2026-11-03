package com.tims.gateway.filter;

import cn.dev33.satoken.stp.StpUtil;
import org.springframework.cloud.gateway.filter.GatewayFilterChain;
import org.springframework.cloud.gateway.filter.GlobalFilter;
import org.springframework.core.Ordered;
import org.springframework.http.server.reactive.ServerHttpRequest;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ServerWebExchange;
import reactor.core.publisher.Mono;

/**
 * 租户头透传过滤器（M2 批一）：
 * - 无条件剥离客户端传入的 X-Tenant-Id（禁止信任客户端传值）
 * - 凭登录 token 从 Sa-Token 会话（与 ticket-system 共享 Redis）取 tenantId，
 *   有则覆盖写入 X-Tenant-Id 透传给下游；匿名请求（白名单）不携带该头
 */
@Component
public class TenantHeaderFilter implements GlobalFilter, Ordered {

    @Override
    public Mono<Void> filter(ServerWebExchange exchange, GatewayFilterChain chain) {
        ServerHttpRequest.Builder builder = exchange.getRequest().mutate();
        builder.headers(h -> h.remove("X-Tenant-Id"));
        String token = exchange.getRequest().getHeaders().getFirst("Authorization");
        if (token != null && !token.isBlank()) {
            try {
                Object loginId = StpUtil.getLoginIdByToken(token);
                if (loginId != null) {
                    Object tenantId = StpUtil.getSessionByLoginId(loginId).get("tenantId");
                    if (tenantId != null) {
                        final String value = String.valueOf(tenantId);
                        builder.headers(h -> h.set("X-Tenant-Id", value));
                    }
                }
            } catch (Exception ignored) {
                // token 无效/会话缺失：保持剥离状态，由下游鉴权兜底
            }
        }
        return chain.filter(exchange.mutate().request(builder.build()).build());
    }

    @Override
    public int getOrder() {
        return -50;
    }
}
