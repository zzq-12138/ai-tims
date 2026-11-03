package com.tims.ai.config;

import org.springframework.http.HttpRequest;
import org.springframework.http.client.ClientHttpRequestExecution;
import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.http.client.ClientHttpResponse;
import org.springframework.stereotype.Component;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

import jakarta.servlet.http.HttpServletRequest;

import java.io.IOException;

/**
 * 下游调用头透传：X-Tenant-Id（网关注入）与 Authorization（登录态共享 Redis Session）。
 * 异步线程无请求上下文时不下发，由调用方显式补齐租户头。
 */
@Component
public class DownstreamHeaderInterceptor implements ClientHttpRequestInterceptor {

    @Override
    public ClientHttpResponse intercept(HttpRequest request, byte[] body, ClientHttpRequestExecution execution)
            throws IOException {
        ServletRequestAttributes attrs =
                (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        if (attrs != null) {
            HttpServletRequest req = attrs.getRequest();
            copy(req, request, "X-Tenant-Id");
            copy(req, request, "Authorization");
        }
        return execution.execute(request, body);
    }

    private void copy(HttpServletRequest req, HttpRequest target, String name) {
        String v = req.getHeader(name);
        if (!target.getHeaders().containsKey(name) && v != null && !v.isBlank()) {
            target.getHeaders().set(name, v);
        }
    }
}
