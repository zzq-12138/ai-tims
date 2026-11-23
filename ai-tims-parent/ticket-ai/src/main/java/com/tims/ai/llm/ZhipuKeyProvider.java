package com.tims.ai.llm;

import com.tims.ai.apikey.AiTenantContext;
import com.tims.ai.apikey.ApiKeyService;
import com.tims.ai.config.AiProperties;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.context.annotation.Lazy;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;

/**
 * 智谱密钥提供者：
 * 1. 租户在管理页配置了 Key（解密后非空）→ 用租户的；
 * 2. 否则回落到环境变量 LLM_API_KEY，再读 ~/secrets/zhipu_api_key。
 * 租户 Key 每次实时查库，管理页改完立即生效；默认 Key 只加载一次。
 * 日志仅打印尾 4 位，禁止明文。
 */
@Component
public class ZhipuKeyProvider {

    private static final Logger log = LoggerFactory.getLogger(ZhipuKeyProvider.class);

    private final AiProperties props;
    private final ApiKeyService apiKeyService;
    private volatile String cached;
    private volatile boolean loaded;

    public ZhipuKeyProvider(AiProperties props, @Lazy ApiKeyService apiKeyService) {
        this.props = props;
        this.apiKeyService = apiKeyService;
    }

    /** 当前线程所属租户优先（由 ChatService/AssistantService 在调用前设置） */
    public String getKey() {
        return getKey(AiTenantContext.get());
    }

    public String getKey(Long tenantId) {
        if (tenantId != null) {
            String tenantKey = apiKeyService.resolve(tenantId);
            if (StringUtils.hasText(tenantKey)) {
                return tenantKey.trim();
            }
        }
        return defaultKey();
    }

    private String defaultKey() {
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
                log.info("[llm] 默认智谱密钥已加载，尾号 ****{}", cached.substring(Math.max(0, cached.length() - 4)));
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
