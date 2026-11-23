package com.tims.ai.controller;

import com.tims.ai.observe.AiObserveService;
import com.tims.ai.prompt.AiPromptVersion;
import com.tims.ai.prompt.PromptRegistry;
import com.tims.ai.util.AdminGuard;
import com.tims.ai.util.CurrentUser;
import com.tims.common.api.Result;
import com.tims.common.exception.BizException;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 可观测性接口（前端观测面板）：
 * GET  /api/ai/observe/overview   调用量/token/费用/P50-P95/失败与拦截/趋势/分模型分场景
 * GET  /api/ai/observe/calls      调用列表（分页 + 时间/用户/场景/模型/状态过滤）
 * GET  /api/ai/observe/calls/{id} 单条详情（含同 traceId 工具链与 prompt 版本内容）
 * GET  /api/ai/observe/prompts    prompt 版本列表（只读）
 * GET  /api/ai/observe/prompts/{id}
 * POST /api/ai/observe/prompts    新增 prompt 版本并生效（管理员）
 */
@RestController
@RequestMapping("/api/ai/observe")
public class AiObserveController {

    private static final DateTimeFormatter FMT = DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss");
    private static final DateTimeFormatter DAY = DateTimeFormatter.ofPattern("yyyy-MM-dd");

    private final AiObserveService observeService;
    private final PromptRegistry promptRegistry;

    public AiObserveController(AiObserveService observeService, PromptRegistry promptRegistry) {
        this.observeService = observeService;
        this.promptRegistry = promptRegistry;
    }

    @GetMapping("/overview")
    public Result<Map<String, Object>> overview(
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to,
            @RequestParam(required = false) Long userId,
            @RequestParam(required = false) String scene,
            @RequestParam(required = false) String model,
            @RequestParam(required = false) String status) {
        AdminGuard.requireAnyRole("ADMIN", "ENGINEER");
        Long tid = CurrentUser.tenantId();
        return Result.ok(observeService.overview(tid, filter(from, to, userId, scene, model, status)));
    }

    @GetMapping("/calls")
    public Result<Map<String, Object>> calls(
            @RequestParam(defaultValue = "1") int page,
            @RequestParam(defaultValue = "20") int size,
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to,
            @RequestParam(required = false) Long userId,
            @RequestParam(required = false) String scene,
            @RequestParam(required = false) String model,
            @RequestParam(required = false) String status) {
        AdminGuard.requireAnyRole("ADMIN", "ENGINEER");
        Long tid = CurrentUser.tenantId();
        return Result.ok(observeService.calls(tid, filter(from, to, userId, scene, model, status), page, size));
    }

    @GetMapping("/calls/{id}")
    public Result<Map<String, Object>> detail(@PathVariable Long id) {
        AdminGuard.requireAnyRole("ADMIN", "ENGINEER");
        Map<String, Object> detail = observeService.detail(CurrentUser.tenantId(), id);
        if (detail == null) {
            throw new BizException(40401, "调用记录不存在");
        }
        return Result.ok(detail);
    }

    @GetMapping("/prompts")
    public Result<List<AiPromptVersion>> prompts(@RequestParam(required = false) String scene) {
        AdminGuard.requireAnyRole("ADMIN", "ENGINEER");
        return Result.ok(promptRegistry.list(CurrentUser.tenantId(), scene));
    }

    @GetMapping("/prompts/{id}")
    public Result<AiPromptVersion> prompt(@PathVariable Long id) {
        AdminGuard.requireAnyRole("ADMIN", "ENGINEER");
        AiPromptVersion v = promptRegistry.byId(CurrentUser.tenantId(), id);
        if (v == null) {
            throw new BizException(40401, "prompt 版本不存在");
        }
        return Result.ok(v);
    }

    /** 新增版本并立即生效；旧版本保留，历史调用仍能反查当时内容 */
    @PostMapping("/prompts")
    public Result<Map<String, Object>> archivePrompt(@RequestBody Map<String, String> body) {
        AdminGuard.requireAdmin();
        String scene = body.get("scene");
        String content = body.get("content");
        if (scene == null || scene.isBlank() || content == null || content.isBlank()) {
            throw new BizException(40001, "scene 与 content 必填");
        }
        Long tid = CurrentUser.tenantId();
        String version = body.get("version");
        if (version == null || version.isBlank()) {
            version = scene.toLowerCase() + "-v" + (promptRegistry.list(tid, scene).size() + 1);
        }
        AiPromptVersion saved = promptRegistry.archive(tid, scene.trim(), version.trim(), content,
                CurrentUser.id());
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("id", saved.getId());
        out.put("scene", saved.getScene());
        out.put("version", saved.getVersion());
        out.put("active", true);
        return Result.ok(out);
    }

    private AiObserveService.Filter filter(String from, String to, Long userId,
                                           String scene, String model, String status) {
        return new AiObserveService.Filter(parse(from, LocalDate.now().minusDays(6).atStartOfDay(), false),
                parse(to, LocalDateTime.now(), true), userId, blank(scene), blank(model), blank(status));
    }

    private LocalDateTime parse(String v, LocalDateTime fallback, boolean endOfDay) {
        if (v == null || v.isBlank()) {
            return fallback;
        }
        String s = v.trim();
        try {
            if (s.length() == 10) {
                LocalDate d = LocalDate.parse(s, DAY);
                return endOfDay ? d.plusDays(1).atStartOfDay().minusNanos(1) : d.atStartOfDay();
            }
            return LocalDateTime.parse(s.replace('T', ' '), FMT);
        } catch (Exception e) {
            return fallback;
        }
    }

    private String blank(String v) {
        return v == null || v.isBlank() ? null : v.trim();
    }
}
