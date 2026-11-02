package com.tims.gateway.controller;

import com.tims.common.api.Result;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * M0 存活探针：GET /api/gateway/ping（WebFlux 环境同样生效）。
 */
@RestController
@RequestMapping("/api/gateway")
public class PingController {

    @GetMapping("/ping")
    public Result<String> ping() {
        return Result.ok("ticket-gateway pong");
    }
}
