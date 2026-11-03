package com.tims.system.config;

import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;

/**
 * 密码编码器：任务书指定标准 spring-security-crypto 的 BCryptPasswordEncoder，
 * 禁明文、禁自写 MD5。种子数据的 $2a$ hash 与该实现兼容，无需迁移。
 */
@Configuration
public class PasswordConfig {

    @Bean
    public BCryptPasswordEncoder passwordEncoder() {
        return new BCryptPasswordEncoder();
    }
}
