package com.tims.knowledge.config;

import cn.dev33.satoken.stp.StpUtil;
import jakarta.servlet.http.HttpServletRequest;
import org.springframework.web.context.request.RequestAttributes;
import org.springframework.web.context.request.RequestContextHolder;
import org.springframework.web.context.request.ServletRequestAttributes;

/**
 * 租户上下文解析（与 ticket-order 同口径，M3）。
 * 优先级：线程内显式覆盖（MQ 消费者） → 登录态 Sa-Token 会话 tenantId → 网关透传 X-Tenant-Id → 兜底 1。
 */
public final class TenantContext {

    private static final ThreadLocal<Long> OVERRIDE = new ThreadLocal<>();

    private TenantContext() {
    }

    /** MQ 消费线程无 Web 上下文，需按事件里的 tenantId 显式覆盖；务必 try/finally 清理 */
    public static void setOverride(Long tenantId) {
        if (tenantId == null) {
            OVERRIDE.remove();
        } else {
            OVERRIDE.set(tenantId);
        }
    }

    public static void clearOverride() {
        OVERRIDE.remove();
    }

    public static Long resolve() {
        Long override = OVERRIDE.get();
        if (override != null) {
            return override;
        }
        try {
            if (StpUtil.isLogin()) {
                Object v = StpUtil.getSession().get("tenantId");
                if (v instanceof Long l) return l;
                if (v instanceof Integer i) return i.longValue();
            }
        } catch (Exception ignored) {
            // 无 Web 上下文时忽略
        }
        RequestAttributes ra = RequestContextHolder.getRequestAttributes();
        if (ra instanceof ServletRequestAttributes sra) {
            HttpServletRequest req = sra.getRequest();
            String h = req.getHeader("X-Tenant-Id");
            if (h != null && h.matches("\\d+")) {
                return Long.parseLong(h);
            }
        }
        return 1L;
    }
}
