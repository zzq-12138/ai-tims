package com.tims.knowledge.service;

import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;
import java.util.concurrent.ThreadPoolExecutor;
import java.util.concurrent.atomic.AtomicLong;

/**
 * M6 抽取积压可观测指标：排队数、处理中数、平均等待时长、失败/重试/拒绝数、队列峰值。
 * 由 GET /internal/kb/extract/queue-stats 直接暴露，供压测与论文取数（不走网关，避免鉴权干扰）。
 */
@Component
public class ExtractQueueMetrics {

    private final ThreadPoolExecutor executor;

    private final AtomicLong submitted = new AtomicLong();
    private final AtomicLong completed = new AtomicLong();
    private final AtomicLong failed = new AtomicLong();
    private final AtomicLong retried = new AtomicLong();
    private final AtomicLong rejected = new AtomicLong();
    private final AtomicLong waitCount = new AtomicLong();
    private final AtomicLong waitTotalMs = new AtomicLong();
    private final AtomicLong waitMaxMs = new AtomicLong();

    private volatile long peakQueueDepth;
    private volatile long peakActive;

    public ExtractQueueMetrics(@Qualifier("extractExecutor") ThreadPoolExecutor executor) {
        this.executor = executor;
    }

    /** 每秒采样一次，记录队列/线程峰值（队列瞬时值本身在 snapshot 里实时读取） */
    @Scheduled(fixedDelay = 1000, initialDelay = 1000)
    public void samplePeak() {
        long queue = executor.getQueue().size();
        long active = executor.getActiveCount();
        if (queue > peakQueueDepth) {
            peakQueueDepth = queue;
        }
        if (active > peakActive) {
            peakActive = active;
        }
    }

    public void recordSubmit() {
        submitted.incrementAndGet();
    }

    public void recordReject() {
        rejected.incrementAndGet();
    }

    public void recordRetry() {
        retried.incrementAndGet();
    }

    public void recordSuccess() {
        completed.incrementAndGet();
    }

    public void recordFailure() {
        failed.incrementAndGet();
    }

    /** 任务真正开始执行时调用，waitMs = 入队 → 开始执行的排队时长 */
    public void recordStart(long waitMs) {
        waitCount.incrementAndGet();
        waitTotalMs.addAndGet(Math.max(0, waitMs));
        waitMaxMs.accumulateAndGet(Math.max(0, waitMs), Math::max);
    }

    public Map<String, Object> snapshot() {
        Map<String, Object> m = new LinkedHashMap<>();
        m.put("queueDepth", executor.getQueue().size());
        m.put("active", executor.getActiveCount());
        m.put("poolSize", executor.getPoolSize());
        m.put("peakQueueDepth", peakQueueDepth);
        m.put("peakActive", peakActive);
        m.put("submitted", submitted.get());
        m.put("completed", completed.get());
        m.put("failed", failed.get());
        m.put("retried", retried.get());
        m.put("rejected", rejected.get());
        long cnt = waitCount.get();
        m.put("avgWaitMs", cnt == 0 ? 0 : waitTotalMs.get() / cnt);
        m.put("maxWaitMs", waitMaxMs.get());
        m.put("completedTasks", executor.getCompletedTaskCount());
        return m;
    }
}
