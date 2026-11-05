package com.tims.ai.chat;

import com.tims.ai.util.CurrentUser;
import com.tims.common.api.Result;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * AI 工单助手会话（M6 问题8）：
 * 当前用户一律从 Sa-Token 登录会话解析（不信任客户端 userId），租户取网关透传 X-Tenant-Id。
 * GET    /api/ai/chat/sessions                    会话列表
 * POST   /api/ai/chat/sessions                    新建
 * PUT    /api/ai/chat/sessions/{id}               重命名
 * DELETE /api/ai/chat/sessions/{id}               删除（软删）
 * GET    /api/ai/chat/sessions/{id}/messages      会话消息（按 tenant+user 校验归属）
 */
@RestController
@RequestMapping("/api/ai/chat/sessions")
public class AiChatSessionController {

    private final AiChatSessionService sessionService;

    public AiChatSessionController(AiChatSessionService sessionService) {
        this.sessionService = sessionService;
    }

    @GetMapping
    public Result<List<AiChatSession>> list() {
        return Result.ok(sessionService.list(CurrentUser.tenantId(), CurrentUser.id()));
    }

    @PostMapping
    public Result<AiChatSession> create(@RequestBody(required = false) Map<String, Object> body) {
        String title = body == null || body.get("title") == null ? null : String.valueOf(body.get("title"));
        return Result.ok(sessionService.create(CurrentUser.tenantId(), CurrentUser.id(), title));
    }

    @PutMapping("/{id}")
    public Result<AiChatSession> rename(@PathVariable Long id,
                                        @RequestBody Map<String, Object> body) {
        String title = body == null || body.get("title") == null ? null : String.valueOf(body.get("title"));
        return Result.ok(sessionService.rename(CurrentUser.tenantId(), CurrentUser.id(), id, title));
    }

    @DeleteMapping("/{id}")
    public Result<Boolean> delete(@PathVariable Long id) {
        sessionService.delete(CurrentUser.tenantId(), CurrentUser.id(), id);
        return Result.ok(true);
    }

    @GetMapping("/{id}/messages")
    public Result<List<AiChatMessage>> messages(@PathVariable Long id) {
        return Result.ok(sessionService.messages(CurrentUser.tenantId(), CurrentUser.id(), id));
    }
}
