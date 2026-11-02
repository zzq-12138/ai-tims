package com.tims.common.enums;

/**
 * 错误码段位（任务书 2.5）：
 * common 10xxx / system 11xxx / order 20xxx / knowledge 30xxx / ai 40xxx / push 50xxx。
 * 各服务业务错误码在对应段位内自行扩展（如 order 非法状态迁移 = 20401）。
 */
public enum ErrorCode {

    SUCCESS(0, "success"),

    // ===== common 10xxx =====
    BAD_REQUEST(10400, "请求参数错误"),
    UNAUTHORIZED(10401, "未登录或凭证失效"),
    FORBIDDEN(10403, "无访问权限"),
    NOT_FOUND(10404, "资源不存在"),
    CONFLICT(10409, "资源冲突"),
    INTERNAL_ERROR(10500, "系统内部错误");

    private final int code;

    private final String message;

    ErrorCode(int code, String message) {
        this.code = code;
        this.message = message;
    }

    public int getCode() {
        return code;
    }

    public String getMessage() {
        return message;
    }
}
