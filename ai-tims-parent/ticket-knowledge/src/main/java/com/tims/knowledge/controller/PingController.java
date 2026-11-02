package com.tims.knowledge.controller;

import com.tims.common.api.Result;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * M0 存活探针：GET /api/kb/ping（网关路由前缀按任务书 3.2 使用 /api/kb）。
 */
@RestController
@RequestMapping("/api/kb")
public class PingController {

    @GetMapping("/ping")
    public Result<String> ping() {
        return Result.ok("ticket-knowledge pong");
    }
}
