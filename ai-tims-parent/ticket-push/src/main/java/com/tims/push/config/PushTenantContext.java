package com.tims.push.config;

/**
 * 推送服务租户上下文：MQ 消费线程 / 降级线程池由事件体注入，
 * HTTP 请求无登录态时兜底 1（单租户阶段恒为 1，与 order/kb 同口径）。
 */
public final class PushTenantContext {

    private static final ThreadLocal<Long> TENANT = new ThreadLocal<>();

    private PushTenantContext() {
    }

    public static void set(Long tenantId) {
        TENANT.set(tenantId == null ? 1L : tenantId);
    }

    public static Long resolve() {
        Long v = TENANT.get();
        return v == null ? 1L : v;
    }

    public static void clear() {
        TENANT.remove();
    }
}
