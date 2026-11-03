package com.tims.push.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;
import org.springframework.web.client.RestTemplate;

/**
 * push 启动预热（M4）：LoadBalanced RestTemplate 首次调用含 Nacos 服务发现 + HTTP 栈初始化，
 * 实测首笔消费冷启动 ~3s（之后 ~500ms）。启动即打一次 kb ping，消除首笔工单推送毛刺，
 * 保障「建单→知识卡片」P95 ≤ 1s。
 */
@Component
public class PushWarmupRunner implements ApplicationRunner {

    private static final Logger log = LoggerFactory.getLogger(PushWarmupRunner.class);

    private final RestTemplate kbRestTemplate;

    public PushWarmupRunner(RestTemplate kbRestTemplate) {
        this.kbRestTemplate = kbRestTemplate;
    }

    @Override
    public void run(ApplicationArguments args) {
        Thread t = new Thread(() -> {
            for (int i = 0; i < 2; i++) { // 两次：首次建 LoadBalancer 缓存，二次建 HTTP keep-alive
                try {
                    long s = System.currentTimeMillis();
                    kbRestTemplate.getForEntity("http://ticket-knowledge/api/kb/ping", String.class);
                    log.info("[预热] kb 调用链路第{}次完成，耗时 {}ms", i + 1, System.currentTimeMillis() - s);
                } catch (Exception e) {
                    log.warn("[预热] kb 预热失败（不影响运行）: {}", e.getMessage());
                }
            }
        }, "push-warmup");
        t.setDaemon(true);
        t.start();
    }
}
