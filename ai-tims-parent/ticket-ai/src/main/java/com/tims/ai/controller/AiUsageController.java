package com.tims.ai.controller;

import com.tims.ai.usage.AiCallLog;
import com.tims.ai.usage.AiUsageService;
import com.tims.common.api.Result;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 调用观测接口（M5）：最近 N 次调用 + 累计 token，用于估算 ¥18 配额余量。
 * GET /api/ai/usage/recent?limit=20
 * GET /api/ai/usage/summary
 */
@RestController
@RequestMapping("/api/ai/usage")
public class AiUsageController {

    private final AiUsageService usageService;

    public AiUsageController(AiUsageService usageService) {
        this.usageService = usageService;
    }

    @GetMapping("/recent")
    public Result<List<AiCallLog>> recent(@RequestParam(defaultValue = "20") int limit,
                                          @RequestHeader(value = "X-Tenant-Id", required = false) String tenant) {
        return Result.ok(usageService.recent(tenantId(tenant), limit));
    }

    @GetMapping("/summary")
    public Result<Map<String, Object>> summary(
            @RequestHeader(value = "X-Tenant-Id", required = false) String tenant) {
        return Result.ok(usageService.summary(tenantId(tenant)));
    }

    private Long tenantId(String header) {
        try {
            return header == null || header.isBlank() ? 1L : Long.parseLong(header.trim());
        } catch (NumberFormatException e) {
            return 1L;
        }
    }
}
