package com.tims.ai.util;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/** 当前请求的租户 / 登录态读取（网关已注入 X-Tenant-Id、只透传 Authorization） */
public final class RequestUtils {

    private RequestUtils() {
    }

    public static Long tenantId() {
        String h = header("X-Tenant-Id");
        try {
            return h == null || h.isBlank() ? 1L : Long.parseLong(h.trim());
        } catch (NumberFormatException e) {
            return 1L;
        }
    }

    public static String authorization() {
        return header("Authorization");
    }

    private static String header(String name) {
        ServletRequestAttributes attrs = (ServletRequestAttributes) RequestContextHolder.getRequestAttributes();
        if (attrs == null) {
            return null;
        }
        HttpServletRequest req = attrs.getRequest();
        return req == null ? null : req.getHeader(name);
    }
}
