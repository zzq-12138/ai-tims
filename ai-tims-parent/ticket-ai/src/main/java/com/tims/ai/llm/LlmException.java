package com.tims.ai.llm;

/**
 * LLM 调用异常：code 走 40xxx 段位，消息直达前端（不静默失败）。
 */
public class LlmException extends RuntimeException {

    private final int code;

    public LlmException(int code, String message) {
        super(message);
        this.code = code;
    }

    public int getCode() {
        return code;
    }
}
