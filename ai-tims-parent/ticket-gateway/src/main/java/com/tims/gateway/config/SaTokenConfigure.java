package com.tims.gateway.config;

import cn.dev33.satoken.context.SaHolder;
import cn.dev33.satoken.reactor.filter.SaReactorFilter;
import cn.dev33.satoken.router.SaRouter;
import cn.dev33.satoken.stp.StpUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.common.api.Result;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.Collection;

/**
 * Gateway 全局鉴权过滤器（任务书 M1）：
 * 白名单外一律 checkLogin；未登录返回 HTTP 401 + 统一 Result{code=10401}。
 * M6 角色矩阵叠加路由级粗粒度守卫（403 + code=10403）：
 * 用户/角色/部门管理 → ADMIN；抽取审核 → ADMIN/REVIEWER。
 * 登录时角色码已签入会话；旧会话无 roles 时放行至接口级守卫兜底，避免升级后强制全员重登。
 * 白名单：登录接口、六服务 ping、actuator、favicon。
 */
@Configuration
public class SaTokenConfigure {

    private static final String[] WHITELIST = {
            "/api/auth/login",
            "/api/auth/register",
            "/api/auth/code",
            "/api/auth/debug/**",
            "/api/gateway/ping",
            "/api/system/ping",
            "/api/order/ping",
            "/api/kb/ping",
            "/api/ai/ping",
            "/api/push/ping",
            "/actuator/**",
            "/favicon.ico",
            // M4：WS 握手（浏览器 WebSocket API 无法携带 Authorization 头），
            // 鉴权由 ticket-push 的 AuthHandshakeInterceptor 用 ?token= 参数完成（Sa-Token 会话共享校验）
            "/ws/**"
    };

    @Bean
    public SaReactorFilter saReactorFilter(ObjectMapper objectMapper) {
        return new SaReactorFilter()
                .addInclude("/**")
                .setAuth(obj -> {
                    SaRouter.match("/**")
                            .notMatch(WHITELIST)
                            .check(r -> StpUtil.checkLogin());
                    SaRouter.match("/api/system/user/**", "/api/system/role/**", "/api/system/dept/**")
                            .check(r -> requireAnyRole("ADMIN"));
                    SaRouter.match("/api/kb/extraction/**")
                            .check(r -> requireAnyRole("ADMIN", "REVIEWER"));
                })
                .setError(e -> {
                    boolean forbidden = e instanceof BizException be
                            && be.getCode() == ErrorCode.FORBIDDEN.getCode();
                    SaHolder.getResponse().setStatus(forbidden ? 403 : 401);
                    return toJson(objectMapper, forbidden ? ErrorCode.FORBIDDEN : ErrorCode.UNAUTHORIZED);
                });
    }

    /** 路由级角色守卫：读取登录会话里的角色码；无 roles（旧会话）时放行，由接口级守卫兜底 */
    private void requireAnyRole(String... allowed) {
        Object cached = StpUtil.getSession().get("roles");
        if (!(cached instanceof Collection<?> roles)) {
            return;
        }
        for (String role : allowed) {
            if (roles.contains(role)) {
                return;
            }
        }
        throw new BizException(ErrorCode.FORBIDDEN, "当前角色无权访问该接口");
    }

    private String toJson(ObjectMapper objectMapper, ErrorCode code) {
        try {
            return objectMapper.writeValueAsString(Result.fail(code));
        } catch (Exception ex) {
            return "{\"code\":" + code.getCode() + ",\"message\":\"" + code.getMessage() + "\",\"data\":null}";
        }
    }
}
