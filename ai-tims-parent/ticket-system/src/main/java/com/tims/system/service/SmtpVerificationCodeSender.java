package com.tims.system.service;

import jakarta.mail.internet.MimeMessage;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.mail.javamail.JavaMailSender;
import org.springframework.mail.javamail.MimeMessageHelper;
import org.springframework.stereotype.Component;

/**
 * SMTP 真实发信实现（QQ 企业个人邮箱 smtp.qq.com:465 SSL）。
 * 授权码经 spring.mail.password 从环境变量 SMTP_AUTH 注入（~/secrets/smtp_auth，不进 git）。
 * 真实发信联调安排在 M2，本轮保证可配置、可装配。
 */
@Component
@ConditionalOnProperty(name = "tims.verification.sender", havingValue = "smtp")
public class SmtpVerificationCodeSender implements VerificationCodeSender {

    private static final Logger log = LoggerFactory.getLogger(SmtpVerificationCodeSender.class);

    private final JavaMailSender mailSender;

    @Value("${tims.verification.mail.from}")
    private String from;

    @Value("${tims.verification.mail.from-name}")
    private String fromName;

    public SmtpVerificationCodeSender(JavaMailSender mailSender) {
        this.mailSender = mailSender;
    }

    @Override
    public void send(String email, String code) {
        try {
            MimeMessage message = mailSender.createMimeMessage();
            MimeMessageHelper helper = new MimeMessageHelper(message, false, "UTF-8");
            helper.setFrom(from, fromName);
            helper.setTo(email);
            helper.setSubject("AI-TIMS 注册验证码");
            helper.setText("""
                    <p>您好！您正在注册 AI-TIMS 智能工单系统，验证码为：</p>
                    <p style="font-size:20px;font-weight:bold;letter-spacing:4px;">%s</p>
                    <p>验证码 5 分钟内有效，请勿泄露给他人。若非本人操作，请忽略本邮件。</p>
                    """.formatted(code), true);
            mailSender.send(message);
            log.info("[SMTP] 验证码邮件已发送至 {}", email);
        } catch (Exception e) {
            log.error("[SMTP] 验证码邮件发送失败: {}", email, e);
            throw new IllegalStateException("验证码邮件发送失败", e);
        }
    }
}
