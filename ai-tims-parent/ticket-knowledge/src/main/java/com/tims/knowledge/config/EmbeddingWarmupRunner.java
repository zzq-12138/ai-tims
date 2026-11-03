package com.tims.knowledge.config;

import com.tims.knowledge.service.EmbeddingService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

import java.util.List;

/**
 * embedding 冷启动预热（M4）：推送链路 P95 ≤ 1s 的关键路径在检索段，
 * 智谱 embedding-3 首次调用含 TLS 握手/连接池建立约 2-3s，
 * 服务启动即后台预热一次，消除首笔业务检索的冷启动毛刺。
 */
@Component
public class EmbeddingWarmupRunner implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(EmbeddingWarmupRunner.class);

    private final EmbeddingService embeddingService;

    public EmbeddingWarmupRunner(EmbeddingService embeddingService) {
        this.embeddingService = embeddingService;
    }

    @Override
    public void run(ApplicationArguments args) {
        Thread t = new Thread(() -> {
            try {
                long s = System.currentTimeMillis();
                embeddingService.embed(List.of("warmup"));
                log.info("[预热] embedding 冷启动完成，耗时 {}ms", System.currentTimeMillis() - s);
            } catch (Exception e) {
                log.warn("[预热] embedding 预热失败（不影响运行，首次业务调用会自愈）: {}", e.getMessage());
            }
        }, "embedding-warmup");
        t.setDaemon(true);
        t.start();
    }
}
