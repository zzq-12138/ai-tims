package com.tims.ai.controller;

import com.tims.ai.llm.LlmException;
import com.tims.common.api.Result;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * AI 域异常：LLM 不可用/超时返回 402xx 业务码（HTTP 200），显式告知前端，不静默失败。
 */
@RestControllerAdvice
public class AiExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(AiExceptionHandler.class);

    @ExceptionHandler(LlmException.class)
    public ResponseEntity<Result<Void>> handleLlm(LlmException e) {
        log.warn("[ai] LLM 调用失败 code={} msg={}", e.getCode(), e.getMessage());
        return ResponseEntity.status(HttpStatus.OK).body(Result.fail(e.getCode(), e.getMessage()));
    }
}
