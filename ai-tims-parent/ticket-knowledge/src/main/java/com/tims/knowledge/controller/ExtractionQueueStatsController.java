package com.tims.knowledge.controller;

import com.tims.common.api.Result;
import com.tims.knowledge.service.ExtractQueueMetrics;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * M6 抽取队列观测端点（内部直连 :8103，不经网关）：
 * GET /internal/kb/extract/queue-stats → 排队数/处理中/均值等待/失败/重试/拒绝/峰值。
 */
@RestController
@RequestMapping("/internal/kb/extract")
public class ExtractionQueueStatsController {

    private final ExtractQueueMetrics metrics;

    public ExtractionQueueStatsController(ExtractQueueMetrics metrics) {
        this.metrics = metrics;
    }

    @GetMapping("/queue-stats")
    public Result<Map<String, Object>> queueStats() {
        return Result.ok(metrics.snapshot());
    }
}
