package com.tims.ai.apikey;

/**
 * 当前 AI 调用所属租户（ThreadLocal）。
 * 只在「真正发起模型/向量请求」的最小范围内设置并清理，非 AI 请求不会误用其他租户的 Key。
 */
public final class AiTenantContext {

    private static final ThreadLocal<Long> HOLDER = new ThreadLocal<>();

    private AiTenantContext() {
    }

    public static void set(Long tenantId) {
        if (tenantId == null) {
            HOLDER.remove();
        } else {
            HOLDER.set(tenantId);
        }
    }

    public static Long get() {
        return HOLDER.get();
    }

    public static void clear() {
        HOLDER.remove();
    }
}
