package com.tims.ai.chat;

import com.tims.common.api.Result;
import com.tims.common.exception.BizException;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * AI 工单助手会话（M6 问题8）：
 * GET    /api/ai/chat/sessions?userId=            会话列表（tenant 由网关透传）
 * POST   /api/ai/chat/sessions                    新建
 * PUT    /api/ai/chat/sessions/{id}               重命名
 * DELETE /api/ai/chat/sessions/{id}?userId=       删除（软删）
 * GET    /api/ai/chat/sessions/{id}/messages?userId=  会话消息（按 tenant+user 校验归属）
 */
@RestController
@RequestMapping("/api/ai/chat/sessions")
public class AiChatSessionController {

    private final AiChatSessionService sessionService;

    public AiChatSessionController(AiChatSessionService sessionService) {
        this.sessionService = sessionService;
    }

    @GetMapping
    public Result<List<AiChatSession>> list(@RequestParam(required = false) Long userId,
                                            @RequestHeader(value = "X-Tenant-Id", required = false) String tenant) {
        return Result.ok(sessionService.list(tenantId(tenant), userId));
    }

    @PostMapping
    public Result<AiChatSession> create(@RequestBody Map<String, Object> body,
                                        @RequestHeader(value = "X-Tenant-Id", required = false) String tenant) {
        Long userId = longOf(body.get("userId"));
        String title = body.get("title") == null ? null : String.valueOf(body.get("title"));
        return Result.ok(sessionService.create(tenantId(tenant), userId, title));
    }

    @PutMapping("/{id}")
    public Result<AiChatSession> rename(@PathVariable Long id,
                                        @RequestBody Map<String, Object> body,
                                        @RequestHeader(value = "X-Tenant-Id", required = false) String tenant) {
        Long userId = longOf(body.get("userId"));
        String title = body.get("title") == null ? null : String.valueOf(body.get("title"));
        return Result.ok(sessionService.rename(tenantId(tenant), userId, id, title));
    }

    @DeleteMapping("/{id}")
    public Result<Boolean> delete(@PathVariable Long id,
                                  @RequestParam(required = false) Long userId,
                                  @RequestHeader(value = "X-Tenant-Id", required = false) String tenant) {
        sessionService.delete(tenantId(tenant), userId, id);
        return Result.ok(true);
    }

    @GetMapping("/{id}/messages")
    public Result<List<AiChatMessage>> messages(@PathVariable Long id,
                                                @RequestParam(required = false) Long userId,
                                                @RequestHeader(value = "X-Tenant-Id", required = false) String tenant) {
        return Result.ok(sessionService.messages(tenantId(tenant), userId, id));
    }

    private Long longOf(Object v) {
        if (v == null || String.valueOf(v).isBlank()) {
            throw new BizException(10400, "userId 必填");
        }
        try {
            return Long.parseLong(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            throw new BizException(10400, "userId 非法");
        }
    }

    private Long tenantId(String header) {
        try {
            return header == null || header.isBlank() ? 1L : Long.parseLong(header.trim());
        } catch (NumberFormatException e) {
            return 1L;
        }
    }
}
