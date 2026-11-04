package com.tims.knowledge.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.tims.common.api.Result;
import com.tims.knowledge.entity.AiExtracted;
import com.tims.knowledge.entity.KbKnowledge;
import com.tims.knowledge.entity.KbKnowledgeHistory;
import com.tims.knowledge.service.ExtractionReviewService;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * M6 抽取审核中心（网关 /api/kb/** → 本服务）：
 * GET  /api/kb/extraction/page                抽取结果分页（含相似度/差异/建议）
 * GET  /api/kb/extraction/{id}                详情
 * PUT  /api/kb/extraction/{id}                人工补录/编辑
 * POST /api/kb/extraction/{id}/approve        人工确认新建（写 PUBLISHED，10s 内向量同步）
 * GET  /api/kb/extraction/preview/{id}        合并前差异预览（目标原文 / 新内容 / 三种取舍结果）
 * POST /api/kb/extraction/{id}/merge          人工确认合并（先历史快照，再按 mode 取舍正文）
 * POST /api/kb/extraction/{id}/reject         人工驳回/跳过
 * GET  /api/kb/extraction/history/{knowledgeId} 合并留痕
 */
@RestController
@RequestMapping("/api/kb/extraction")
public class ExtractionController {

    private final ExtractionReviewService reviewService;

    public ExtractionController(ExtractionReviewService reviewService) {
        this.reviewService = reviewService;
    }

    @GetMapping("/page")
    public Result<Page<AiExtracted>> page(@RequestParam(defaultValue = "1") long current,
                                          @RequestParam(defaultValue = "10") long size,
                                          @RequestParam(required = false) String status) {
        return Result.ok(reviewService.page(current, size, status));
    }

    @GetMapping("/{id}")
    public Result<AiExtracted> detail(@PathVariable Long id) {
        return Result.ok(reviewService.detail(id));
    }

    @PutMapping("/{id}")
    public Result<AiExtracted> update(@PathVariable Long id, @RequestBody AiExtracted in) {
        return Result.ok(reviewService.update(id, in));
    }

    @PostMapping("/{id}/approve")
    public Result<KbKnowledge> approve(@PathVariable Long id) {
        return Result.ok(reviewService.approve(id));
    }

    /** 合并前差异预览：前端据此展示目标原文与新内容，避免误操作 */
    @GetMapping("/preview/{id}")
    public Result<Map<String, Object>> preview(@PathVariable Long id,
                                               @RequestParam(required = false) Long targetId) {
        return Result.ok(reviewService.mergePreview(id, targetId));
    }

    /** 合并 mode：CONCAT（默认）/ KEEP_ORIGINAL / REPLACE / MERGE（旧口径=CONCAT） */
    @PostMapping("/{id}/merge")
    public Result<KbKnowledge> merge(@PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        Long targetId = null;
        String mode = null;
        if (body != null && body.get("targetId") != null) {
            targetId = Long.parseLong(String.valueOf(body.get("targetId")));
        }
        if (body != null && body.get("mode") != null) {
            mode = String.valueOf(body.get("mode"));
        }
        return Result.ok(reviewService.merge(id, targetId, mode));
    }

    @PostMapping("/{id}/reject")
    public Result<Void> reject(@PathVariable Long id, @RequestBody(required = false) Map<String, Object> body) {
        String reason = body == null || body.get("reason") == null ? null : String.valueOf(body.get("reason"));
        reviewService.reject(id, reason);
        return Result.ok();
    }

    @GetMapping("/history/{knowledgeId}")
    public Result<List<KbKnowledgeHistory>> history(@PathVariable Long knowledgeId) {
        return Result.ok(reviewService.history(knowledgeId));
    }
}
