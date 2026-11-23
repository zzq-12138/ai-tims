package com.tims.ai.fallback;

import com.tims.ai.util.AdminGuard;
import com.tims.common.api.Result;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 兜底配对数据的运营入口（仅 ADMIN）：
 * POST /api/ai/admin/fallback/recompute?includeTest=false  按新口径重算存量
 * GET  /api/ai/admin/fallback/pairs?includeTest=false      查看逐段比对明细
 * 默认排除 is_test=1 的测试数据。
 */
@RestController
@RequestMapping("/api/ai/admin/fallback")
public class FallbackAdminController {

    private final FallbackSuggestionService fallbackService;

    public FallbackAdminController(FallbackSuggestionService fallbackService) {
        this.fallbackService = fallbackService;
    }

    @PostMapping("/recompute")
    public Result<Map<String, Object>> recompute(
            @RequestParam(value = "includeTest", defaultValue = "false") boolean includeTest) {
        AdminGuard.requireAdmin();
        return Result.ok(fallbackService.recompute(includeTest));
    }

    @GetMapping("/pairs")
    public Result<List<Map<String, Object>>> pairs(
            @RequestParam(value = "includeTest", defaultValue = "false") boolean includeTest) {
        AdminGuard.requireAdmin();
        return Result.ok(fallbackService.list(includeTest));
    }
}
