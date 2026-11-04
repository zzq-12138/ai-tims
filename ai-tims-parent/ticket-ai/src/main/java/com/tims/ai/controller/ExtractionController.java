package com.tims.ai.controller;

import com.tims.ai.dto.ExtractRequest;
import com.tims.ai.dto.ExtractResult;
import com.tims.ai.service.ExtractionService;
import com.tims.common.api.Result;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * M6 内部知识抽取接口（仅 ticket-knowledge 的 ticket.closed 消费者调用，网关外部需登录）。
 * POST /api/ai/internal/extract  body=工单摘要，返回结构化知识 + token 用量。
 */
@RestController
@RequestMapping("/api/ai/internal")
public class ExtractionController {

    private final ExtractionService extractionService;

    public ExtractionController(ExtractionService extractionService) {
        this.extractionService = extractionService;
    }

    @PostMapping("/extract")
    public Result<ExtractResult> extract(@RequestBody ExtractRequest req) {
        return Result.ok(extractionService.extract(req.getTenantId(), req));
    }
}
