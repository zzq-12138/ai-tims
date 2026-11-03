package com.tims.knowledge.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.tims.common.api.Result;
import com.tims.knowledge.entity.KbKnowledge;
import com.tims.knowledge.service.KnowledgeService;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * 知识接口（M3，网关 /api/kb/** → 本服务）：
 * GET    /api/kb/knowledge/page            分页（status/deviceType/categoryId/keyword）
 * GET    /api/kb/knowledge/{id}            详情
 * POST   /api/kb/knowledge                 新建（DRAFT）
 * PUT    /api/kb/knowledge/{id}            编辑（version+1，PUBLISHED 编辑后自动重嵌入）
 * DELETE /api/kb/knowledge/{id}            逻辑删除（向量一并撤下）
 * POST   /api/kb/knowledge/{id}/submit     提交审核 DRAFT/REJECTED → PENDING
 * POST   /api/kb/knowledge/{id}/publish    审核 PENDING → PUBLISHED（ADMIN）
 * POST   /api/kb/knowledge/{id}/reject     审核 PENDING → REJECTED（ADMIN，含原因）
 */
@RestController
@RequestMapping("/api/kb/knowledge")
public class KnowledgeController {

    private final KnowledgeService knowledgeService;

    public KnowledgeController(KnowledgeService knowledgeService) {
        this.knowledgeService = knowledgeService;
    }

    @GetMapping("/page")
    public Result<Page<KbKnowledge>> page(@RequestParam(defaultValue = "1") long current,
                                          @RequestParam(defaultValue = "10") long size,
                                          @RequestParam(required = false) String status,
                                          @RequestParam(required = false) String deviceType,
                                          @RequestParam(required = false) Long categoryId,
                                          @RequestParam(required = false) String keyword) {
        return Result.ok(knowledgeService.page(current, size, status, deviceType, categoryId, keyword));
    }

    @GetMapping("/{id}")
    public Result<KbKnowledge> detail(@PathVariable Long id) {
        return Result.ok(knowledgeService.detail(id));
    }

    @PostMapping
    public Result<KbKnowledge> create(@RequestBody KbKnowledge in) {
        return Result.ok(knowledgeService.create(in));
    }

    @PutMapping("/{id}")
    public Result<KbKnowledge> update(@PathVariable Long id, @RequestBody KbKnowledge in) {
        return Result.ok(knowledgeService.update(id, in));
    }

    @DeleteMapping("/{id}")
    public Result<Void> delete(@PathVariable Long id) {
        knowledgeService.delete(id);
        return Result.ok();
    }

    @PostMapping("/{id}/submit")
    public Result<Void> submit(@PathVariable Long id) {
        knowledgeService.submit(id);
        return Result.ok();
    }

    @PostMapping("/{id}/publish")
    public Result<Void> publish(@PathVariable Long id) {
        knowledgeService.publish(id);
        return Result.ok();
    }

    @PostMapping("/{id}/reject")
    public Result<Void> reject(@PathVariable Long id, @RequestBody(required = false) RejectBody body) {
        knowledgeService.reject(id, body == null ? null : body.getReason());
        return Result.ok();
    }

    /** 驳回原因入参 */
    public static class RejectBody {
        private String reason;

        public String getReason() { return reason; }
        public void setReason(String reason) { this.reason = reason; }
    }
}
