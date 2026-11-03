package com.tims.system.service;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.stereotype.Component;

/**
 * 开发默认实现：只写日志，不真实发信。
 * 调试取码走 /api/auth/debug/code（DebugCodeController，仅 mock 模式装配）。
 */
@Component
@ConditionalOnProperty(name = "tims.verification.sender", havingValue = "mock", matchIfMissing = true)
public class MockVerificationCodeSender implements VerificationCodeSender {

    private static final Logger log = LoggerFactory.getLogger(MockVerificationCodeSender.class);

    @Override
    public void send(String email, String code) {
        log.info("[MOCK-验证码] email={}, code={}（开发模式，不真实发信）", email, code);
    }
}
