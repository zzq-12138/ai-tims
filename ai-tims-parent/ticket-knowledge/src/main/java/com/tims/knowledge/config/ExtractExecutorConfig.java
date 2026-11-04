package com.tims.knowledge.config;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import java.util.concurrent.ArrayBlockingQueue;
import java.util.concurrent.RejectedExecutionHandler;
import java.util.concurrent.ThreadFactory;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/**
 * M6 知识抽取异步执行器：把“调 ticket-ai 抽取（单次 9~10s）”从 RabbitMQ 消费线程解耦。
 * 队列必须是有界队列，集中关单高峰时提供背压而不是无限堆积；
 * 默认并发与既有消费并发口径一致（core 16 / max 32），全部参数可环境变量覆盖。
 */
@Configuration
public class ExtractExecutorConfig {

    private static final Logger log = LoggerFactory.getLogger(ExtractExecutorConfig.class);

    @Bean(name = "extractExecutor", destroyMethod = "shutdown")
    public ThreadPoolExecutor extractExecutor(
            @Value("${tims.kb.extract.executor.core-size:16}") int coreSize,
            @Value("${tims.kb.extract.executor.max-size:32}") int maxSize,
            @Value("${tims.kb.extract.executor.queue-capacity:200}") int queueCapacity,
            @Value("${tims.kb.extract.executor.keep-alive-seconds:60}") int keepAliveSeconds,
            @Value("${tims.kb.extract.executor.rejection-policy:CallerRunsPolicy}") String rejectionPolicy) {
        int core = Math.max(1, coreSize);
        int max = Math.max(core, maxSize);
        int queue = Math.max(1, queueCapacity);
        ThreadFactory factory = new ThreadFactory() {
            private final AtomicInteger seq = new AtomicInteger(1);

            @Override
            public Thread newThread(Runnable r) {
                return new Thread(r, "kb-extract-" + seq.getAndIncrement());
            }
        };
        ThreadPoolExecutor executor = new ThreadPoolExecutor(core, max, keepAliveSeconds, TimeUnit.SECONDS,
                new ArrayBlockingQueue<>(queue), factory, rejectionHandler(rejectionPolicy));
        log.info("[extract-pool] core={} max={} queue={} keepAlive={}s rejection={}",
                core, max, queue, keepAliveSeconds, rejectionPolicy);
        return executor;
    }

    /** 拒绝策略按名称可配：CallerRunsPolicy（默认，背压不丢任务）/ AbortPolicy / DiscardPolicy / DiscardOldestPolicy */
    static RejectedExecutionHandler rejectionHandler(String name) {
        String n = name == null ? "" : name.trim().toLowerCase();
        return switch (n) {
            case "abort", "abortpolicy" -> new ThreadPoolExecutor.AbortPolicy();
            case "discard", "discardpolicy" -> new ThreadPoolExecutor.DiscardPolicy();
            case "discardoldest", "discardoldestpolicy" -> new ThreadPoolExecutor.DiscardOldestPolicy();
            default -> new ThreadPoolExecutor.CallerRunsPolicy();
        };
    }
}
