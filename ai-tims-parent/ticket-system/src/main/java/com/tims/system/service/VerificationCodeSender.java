package com.tims.system.service;

/**
 * 验证码发信抽象（2026-11-02 台账决策：邮箱验证码优先，手机号仅保留为注册必填字段）。
 * 实现两套：MockSender（开发默认，写日志+调试接口取码）/ SmtpSender（真实发信，M2 验证）。
 * 由 tims.verification.sender=mock|smtp 切换。
 */
public interface VerificationCodeSender {

    /**
     * 发送注册验证码。
     *
     * @param email 收件邮箱
     * @param code  6 位数字验证码
     */
    void send(String email, String code);
}
