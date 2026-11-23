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
import org.springframework.web.bind.annotation.RequestParam;
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

    /** 撤回前置信息：这一轮会删掉哪些消息、调用过哪些工具、是否含写操作 */
    @GetMapping("/{id}/messages/{messageId}/recall-info")
    public Result<Map<String, Object>> recallInfo(@PathVariable Long id, @PathVariable Long messageId) {
        return Result.ok(sessionService.recallInfo(CurrentUser.tenantId(), CurrentUser.id(), id, messageId));
    }

    /**
     * 撤回本人发送的用户消息 = 物理删除该条 + 它触发的那条 AI 回复。
     * force=false 时若该轮含写操作（工具调用白名单外）返回 10409，前端确认后带 force=true 再删。
     */
    @DeleteMapping("/{id}/messages/{messageId}")
    public Result<Map<String, Object>> deleteMessage(@PathVariable Long id, @PathVariable Long messageId,
                                                     @RequestParam(name = "force", defaultValue = "false") boolean force) {
        return Result.ok(sessionService.deleteRound(CurrentUser.tenantId(), CurrentUser.id(), id, messageId, force));
    }
}
