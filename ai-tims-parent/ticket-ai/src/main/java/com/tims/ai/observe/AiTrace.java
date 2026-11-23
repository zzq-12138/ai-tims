package com.tims.ai.observe;

import java.util.UUID;

/**
 * 调用链 id（ThreadLocal）。同一次问答的父调用与工具调用共用 traceId，
 * 观测面板据此把「父调用 + 工具调用」拼成一条链。
 *
 * 每次请求入口必须 start()，避免线程池复用导致不同请求串链。
 */
public final class AiTrace {

    private static final ThreadLocal<String> HOLDER = new ThreadLocal<>();

    private AiTrace() {
    }

    public static String start() {
        String id = "tr-" + UUID.randomUUID().toString().replace("-", "").substring(0, 20);
        HOLDER.set(id);
        return id;
    }

    public static String id() {
        return HOLDER.get();
    }

    public static void clear() {
        HOLDER.remove();
    }
}
