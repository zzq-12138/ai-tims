package com.tims.ai.llm;

import com.tims.ai.config.AiProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * 智谱密钥提供者：优先环境变量 LLM_API_KEY，其次从 ~/secrets/zhipu_api_key 读取。
 * 密钥只在内存中使用，禁止落库/入 Git/打日志明文（日志仅打印末 4 位）。
 */
@Component
public class ZhipuKeyProvider {

    private static final Logger log = LoggerFactory.getLogger(ZhipuKeyProvider.class);

    private final AiProperties props;
    private volatile String cached;
    private volatile boolean loaded;

    public ZhipuKeyProvider(AiProperties props) {
        this.props = props;
    }

    public String getKey() {
        if (loaded) {
            return cached;
        }
        synchronized (this) {
            if (loaded) {
                return cached;
            }
            String key = props.getApiKey();
            if (!StringUtils.hasText(key)) {
                key = readFileQuietly(props.getApiKeyFile());
            }
            cached = key == null ? "" : key.trim();
            loaded = true;
            if (cached.isEmpty()) {
                log.error("[llm] 未找到智谱 API Key：请设置 LLM_API_KEY 或写入 {}（600 权限）", props.getApiKeyFile());
            } else {
                log.info("[llm] 智谱密钥已加载，尾号 ****{}", cached.substring(Math.max(0, cached.length() - 4)));
            }
        }
        return cached;
    }

    private String readFileQuietly(String file) {
        if (!StringUtils.hasText(file)) {
            return null;
        }
        try {
            Path p = Path.of(file);
            if (!Files.exists(p)) {
                return null;
            }
            return Files.readString(p).trim();
        } catch (IOException e) {
            log.warn("[llm] 读取密钥文件失败: {}", e.getMessage());
            return null;
        }
    }
}
