package com.tims.common.exception;

import com.tims.common.api.Result;
import com.tims.common.enums.ErrorCode;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

/**
 * 全局异常处理：业务异常与未知异常统一转 Result{code, message}。
 * 注解仅依赖 spring-web，兼容 MVC 服务与 Gateway(WebFlux) 两端。
 * HTTP 状态映射：10401→401、10403→403（任务书「401 统一体」验收口径），
 * 其余业务错误保持 HTTP 200 + 业务码。
 */
@RestControllerAdvice
public class GlobalExceptionHandler {

    private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

    @ExceptionHandler(BizException.class)
    public ResponseEntity<Result<Void>> handleBizException(BizException e) {
        log.warn("业务异常: code={}, message={}", e.getCode(), e.getMessage());
        return ResponseEntity.status(toHttpStatus(e.getCode()))
                .body(Result.fail(e.getCode(), e.getMessage()));
    }

    @ExceptionHandler(org.springframework.web.bind.MethodArgumentNotValidException.class)
    public ResponseEntity<Result<Void>> handleValidation(org.springframework.web.bind.MethodArgumentNotValidException e) {
        String msg = e.getBindingResult().getFieldErrors().stream()
                .map(f -> f.getDefaultMessage())
                .findFirst()
                .orElse(ErrorCode.BAD_REQUEST.getMessage());
        log.warn("参数校验失败: {}", msg);
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(Result.fail(ErrorCode.BAD_REQUEST.getCode(), msg));
    }

    @ExceptionHandler(IllegalArgumentException.class)
    public ResponseEntity<Result<Void>> handleIllegalArgument(IllegalArgumentException e) {
        log.warn("参数错误: {}", e.getMessage());
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(Result.fail(ErrorCode.BAD_REQUEST));
    }

    @ExceptionHandler(Exception.class)
    public ResponseEntity<Result<Void>> handleException(Exception e) {
        log.error("系统异常", e);
        return ResponseEntity.status(HttpStatus.INTERNAL_SERVER_ERROR)
                .body(Result.fail(ErrorCode.INTERNAL_ERROR));
    }

    private HttpStatus toHttpStatus(int code) {
        if (code == ErrorCode.UNAUTHORIZED.getCode()) {
            return HttpStatus.UNAUTHORIZED;
        }
        if (code == ErrorCode.FORBIDDEN.getCode()) {
            return HttpStatus.FORBIDDEN;
        }
        if (code == ErrorCode.NOT_FOUND.getCode()) {
            return HttpStatus.NOT_FOUND;
        }
        return HttpStatus.OK;
    }
}
