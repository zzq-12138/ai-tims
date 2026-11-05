package com.tims.ai.util;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/** 当前请求的租户 / 登录态读取（网关已注入 X-Tenant-Id、只透传 Authorization） */
public final class RequestUtils {

    private RequestUtils() {
    }

    public static Long tenantId() {
        Long v = tenantIdOrNull();
        return v == null ? 1L : v;
    }

    /** 网关透传的租户；未携带或非法返回 null（供登录态回退判断） */
    public static Long tenantIdOrNull() {
        String h = header("X-Tenant-Id");
        if (h == null || h.isBlank()) {
            return null;
        }
        try {
            return Long.parseLong(h.trim());
        } catch (NumberFormatException e) {
            return null;
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
