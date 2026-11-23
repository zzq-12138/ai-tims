package com.tims.ai.apikey;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Component;

import javax.crypto.Cipher;
import javax.crypto.spec.GCMParameterSpec;
import javax.crypto.spec.SecretKeySpec;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.util.Base64;

/**
 * API Key 落库加密：AES-256-GCM。
 * 主密钥来自环境变量 AI_KEY_SECRET（tims.ai.key-cipher-secret），不进 Git；
 * 未配置时使用开发默认值并告警——生产必须显式配置。
 */
@Component
public class ApiKeyCipher {

    private static final Logger log = LoggerFactory.getLogger(ApiKeyCipher.class);
    private static final String DEV_SECRET = "tims-ai-dev-secret-change-in-prod";
    private static final int IV_LEN = 12;
    private static final int TAG_BITS = 128;

    private final SecretKeySpec key;
    private final SecureRandom random = new SecureRandom();

    public ApiKeyCipher(@Value("${tims.ai.key-cipher-secret:}") String secret) {
        String raw = (secret == null || secret.isBlank()) ? DEV_SECRET : secret;
        if (secret == null || secret.isBlank()) {
            log.warn("[apikey] 未配置 tims.ai.key-cipher-secret，使用开发默认密钥；生产环境必须设置 AI_KEY_SECRET");
        }
        try {
            this.key = new SecretKeySpec(MessageDigest.getInstance("SHA-256")
                    .digest(raw.getBytes(StandardCharsets.UTF_8)), "AES");
        } catch (Exception e) {
            throw new IllegalStateException("初始化 API Key 加密器失败", e);
        }
    }

    public String encrypt(String plain) {
        try {
            byte[] iv = new byte[IV_LEN];
            random.nextBytes(iv);
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.ENCRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            byte[] out = c.doFinal(plain.getBytes(StandardCharsets.UTF_8));
            return "v1:" + Base64.getEncoder().encodeToString(iv) + ":"
                    + Base64.getEncoder().encodeToString(out);
        } catch (Exception e) {
            throw new IllegalStateException("API Key 加密失败", e);
        }
    }

    public String decrypt(String cipherText) {
        if (cipherText == null || !cipherText.startsWith("v1:")) {
            return null;
        }
        try {
            String[] parts = cipherText.split(":");
            if (parts.length != 3) {
                return null;
            }
            byte[] iv = Base64.getDecoder().decode(parts[1]);
            byte[] data = Base64.getDecoder().decode(parts[2]);
            Cipher c = Cipher.getInstance("AES/GCM/NoPadding");
            c.init(Cipher.DECRYPT_MODE, key, new GCMParameterSpec(TAG_BITS, iv));
            return new String(c.doFinal(data), StandardCharsets.UTF_8);
        } catch (Exception e) {
            log.warn("[apikey] 解密失败（主密钥变更或数据损坏）: {}", e.getMessage());
            return null;
        }
    }

    /** 只展示尾号；长度不足时全遮 */
    public static String tail(String key) {
        if (key == null || key.isBlank()) {
            return "****";
        }
        String s = key.trim();
        return s.length() <= 4 ? "****" : s.substring(s.length() - 4);
    }

    /** 审计日志里最多保留前 4 位 + 尾号，避免明文入日志 */
    public static String masked(String key) {
        if (key == null || key.isBlank()) {
            return "****";
        }
        String s = key.trim();
        if (s.length() <= 8) {
            return "****" + tail(s);
        }
        return s.substring(0, 4) + "****" + tail(s);
    }
}
