package com.tims.ai.fallback;

import com.tims.ai.util.CurrentUser;
import com.tims.common.api.Result;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;

/**
 * C 档兜底建议的处置回填入口（工单关闭/人工补录时调用）。
 * 只记录，不触发任何入库或反馈闭环。
 */
@RestController
@RequestMapping("/api/ai/fallback")
public class FallbackController {

    private final FallbackSuggestionService fallbackService;

    public FallbackController(FallbackSuggestionService fallbackService) {
        this.fallbackService = fallbackService;
    }

    /** 回填实际处置；返回一致性判定结果（consistent 可能为 null：文本过短无法判定） */
    @PostMapping("/{id}/disposition")
    public Result<Map<String, Object>> backfill(@PathVariable("id") Long id,
                                                @RequestBody DispositionRequest request) {
        return Result.ok(fallbackService.backfill(
                CurrentUser.tenantId(), id,
                request == null ? null : request.getActualDisposition(),
                CurrentUser.id()));
    }

    /** 回填请求体 */
    public static class DispositionRequest {
        private String actualDisposition;

        public String getActualDisposition() { return actualDisposition; }
        public void setActualDisposition(String actualDisposition) { this.actualDisposition = actualDisposition; }
    }
}
