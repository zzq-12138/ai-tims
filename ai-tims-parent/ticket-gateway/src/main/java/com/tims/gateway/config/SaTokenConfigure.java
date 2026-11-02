package com.tims.gateway.config;

import cn.dev33.satoken.context.SaHolder;
import cn.dev33.satoken.reactor.filter.SaReactorFilter;
import cn.dev33.satoken.router.SaRouter;
import cn.dev33.satoken.stp.StpUtil;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.common.api.Result;
import com.tims.common.enums.ErrorCode;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

/**
 * Gateway 全局鉴权过滤器（任务书 M1）：
 * 白名单外一律 checkLogin；未登录返回 HTTP 401 + 统一 Result{code=10401}。
 * 白名单：登录接口、六服务 ping、actuator、favicon。
 */
@Configuration
public class SaTokenConfigure {

    private static final String[] WHITELIST = {
            "/api/auth/login",
            "/api/gateway/ping",
            "/api/system/ping",
            "/api/order/ping",
            "/api/kb/ping",
            "/api/ai/ping",
            "/api/push/ping",
            "/actuator/**",
            "/favicon.ico"
    };

    @Bean
    public SaReactorFilter saReactorFilter(ObjectMapper objectMapper) {
        return new SaReactorFilter()
                .addInclude("/**")
                .setAuth(obj -> SaRouter.match("/**")
                        .notMatch(WHITELIST)
                        .check(r -> StpUtil.checkLogin()))
                .setError(e -> {
                    SaHolder.getResponse().setStatus(401);
                    return toJson(objectMapper);
                });
    }

    private String toJson(ObjectMapper objectMapper) {
        try {
            return objectMapper.writeValueAsString(Result.fail(ErrorCode.UNAUTHORIZED));
        } catch (Exception ex) {
            return "{\"code\":10401,\"message\":\"未登录或凭证失效\",\"data\":null}";
        }
    }
}
