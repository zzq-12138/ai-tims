package com.tims.common.constant;

/**
 * 全局基础常量。
 */
public final class Constants {

    /** Sa-Token 请求头（任务书 3.2） */
    public static final String AUTH_HEADER = "satoken";

    /** 全局时区 */
    public static final String TIME_ZONE = "Asia/Shanghai";

    /** MQ topic exchange（M2 起使用，任务书 3.8） */
    public static final String EVENT_EXCHANGE = "ai-tims.event";

    private Constants() {
    }
}
