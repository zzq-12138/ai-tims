package com.tims.system.controller;

import com.tims.common.api.Result;
import com.tims.system.service.RegisterService;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 开发调试接口（仅 mock 发信模式装配，生产 smtp 模式下不存在该 Bean）：
 * 供开发阶段从 Redis 取验证码，免去翻日志。网关白名单仅放 /api/auth/debug/**。
 */
@RestController
@RequestMapping("/api/auth/debug")
@ConditionalOnProperty(name = "tims.verification.sender", havingValue = "mock", matchIfMissing = true)
public class DebugCodeController {

    private final StringRedisTemplate redis;

    public DebugCodeController(StringRedisTemplate redis) {
        this.redis = redis;
    }

    @GetMapping("/code")
    public Result<Map<String, Object>> code(@RequestParam String email) {
        String code = redis.opsForValue().get("tims:reg:code:" + email);
        return Result.ok(Map.of("email", email, "code", code == null ? "" : code));
    }
}
