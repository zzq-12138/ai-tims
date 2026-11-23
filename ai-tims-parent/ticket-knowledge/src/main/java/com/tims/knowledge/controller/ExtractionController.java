package com.tims.knowledge.controller;

import com.baomidou.mybatisplus.extension.plugins.pagination.Page;
import com.tims.common.api.Result;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.knowledge.entity.AiExtracted;
import com.tims.knowledge.entity.KbKnowledge;
import com.tims.knowledge.entity.KbKnowledgeHistory;
import com.tims.knowledge.dto.FallbackIntakeRequest;
import com.tims.knowledge.service.ExtractionReviewService;
import com.tims.knowledge.service.FallbackIntakeService;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeParseException;
import java.util.List;
import java.util.Map;

/**
 * M6 抽取审核中心（网关 /api/kb/** → 本服务）：
 * GET  /api/kb/extraction/page                抽取结果分页（含相似度/差异/建议）
 * GET  /api/kb/extraction/device-types        设备类型下拉选项（取实际数据）
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
    private final FallbackIntakeService fallbackIntakeService;

    /** 服务间共享密钥：必须由环境变量 TIMS_INTERNAL_TOKEN 注入；留空时 intake 接口默认拒绝 */
    @Value("${tims.internal-token:}")
    private String internalToken;

    public ExtractionController(ExtractionReviewService reviewService,
                                FallbackIntakeService fallbackIntakeService) {
        this.reviewService = reviewService;
        this.fallbackIntakeService = fallbackIntakeService;
    }

    /**
     * 抽取结果分页：分页参数统一为 current/size（与 /api/kb/knowledge/page 同口径）。
     * 筛选项：status 精确、title/sourceTicketNo 模糊、deviceType/dedupAction 精确、createTime 区间。
     */
    @GetMapping("/page")
    public Result<Page<AiExtracted>> page(@RequestParam(defaultValue = "1") long current,
                                          @RequestParam(defaultValue = "10") long size,
                                          @RequestParam(required = false) String status,
                                          @RequestParam(required = false) String title,
                                          @RequestParam(required = false) String sourceTicketNo,
                                          @RequestParam(required = false) String deviceType,
                                          @RequestParam(required = false) String dedupAction,
                                          @RequestParam(required = false) String startTime,
                                          @RequestParam(required = false) String endTime) {
        return Result.ok(reviewService.page(current, size, status, title, sourceTicketNo, deviceType,
                dedupAction, parseTime(startTime, "startTime"), parseTime(endTime, "endTime")));
    }

    /** 设备类型下拉选项：取自 ai_extracted 实际数据，避免前端写死 */
    @GetMapping("/device-types")
    public Result<List<String>> deviceTypes() {
        return Result.ok(reviewService.deviceTypes());
    }

    /**
     * 建议→回填：接收 ticket-ai 投递的待审条目（只写 ai_extracted，不直写知识库）。
     * 幂等键为 (tenant_id, source_type=FALLBACK, source_ref_id)；日上限与置信阈值在服务端校验。
     * 服务间调用校验：复用仓库既有 X-Internal-Token 约定；未配置密钥时一律拒绝。
     */
    @PostMapping("/intake/fallback")
    public Result<Map<String, Object>> intakeFallback(
            @RequestHeader(value = "X-Internal-Token", required = false) String token,
            @RequestBody FallbackIntakeRequest req) {
        if (internalToken == null || internalToken.isBlank()
                || token == null || !token.equals(internalToken)) {
            throw new BizException(ErrorCode.FORBIDDEN, "内部接口密钥校验失败");
        }
        return Result.ok(fallbackIntakeService.intake(req));
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

    /** 支持 yyyy-MM-dd（按当天 00:00:00）与 yyyy-MM-dd HH:mm:ss / ISO 两种写法 */
    private static LocalDateTime parseTime(String value, String field) {
        if (value == null || value.isBlank()) {
            return null;
        }
        String v = value.trim();
        try {
            if (v.length() == 10) {
                return LocalDate.parse(v).atStartOfDay();
            }
            return LocalDateTime.parse(v.replace(' ', 'T'));
        } catch (DateTimeParseException e) {
            throw new BizException(10400, field + " 时间格式非法，应为 yyyy-MM-dd HH:mm:ss");
        }
    }
}
