package com.tims.system.controller;

import com.tims.common.api.Result;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * M0 存活探针：GET /api/system/ping。
 */
@RestController
@RequestMapping("/api/system")
public class PingController {

    @GetMapping("/ping")
    public Result<String> ping() {
        return Result.ok("ticket-system pong");
    }
}
