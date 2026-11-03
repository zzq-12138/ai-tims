package com.tims.push.controller;

import com.tims.common.api.Result;
import com.tims.push.service.LatencyService;
import com.tims.push.service.MessageService;
import com.tims.push.ws.WsSessionRegistry;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.Map;

/**
 * 推送 REST 接口（M4，网关 /api/push/**，网关统一登录鉴权）：
 * GET  /api/push/stats?limit=500      端到端时延统计（P50/P95/P99 + 三段均值 + 降级计数）
 * GET  /api/push/online               在线坐席列表（前端在线状态指示）
 * GET  /api/push/messages/unread      未读站内消息（WS 之外的兜底拉取）
 * POST /api/push/messages/read        标记已读 {messageId}
 */
@RestController
@RequestMapping("/api/push")
public class PushController {

    private final LatencyService latencyService;
    private final MessageService messageService;
    private final WsSessionRegistry sessionRegistry;

    public PushController(LatencyService latencyService,
                          MessageService messageService,
                          WsSessionRegistry sessionRegistry) {
        this.latencyService = latencyService;
        this.messageService = messageService;
        this.sessionRegistry = sessionRegistry;
    }

    @GetMapping("/stats")
    public Result<Map<String, Object>> stats(@RequestParam(defaultValue = "500") Integer limit) {
        return Result.ok(latencyService.stats(limit));
    }

    @GetMapping("/online")
    public Result<Map<String, Object>> online() {
        List<Map<String, Object>> users = sessionRegistry.listOnline();
        return Result.ok(Map.of("count", users.size(), "users", users));
    }

    /** 未读站内消息（userId 由网关登录态透传不可用，push 无登录上下文 → 用 query 参数，前端传自己 id） */
    @GetMapping("/messages/unread")
    public Result<List<Map<String, Object>>> unread(@RequestParam Long userId) {
        return Result.ok(messageService.takeUnreadForPush(userId, 1L));
    }

    @PostMapping("/messages/read")
    public Result<Void> markRead(@RequestBody Map<String, Object> body) {
        Object id = body.get("messageId");
        if (id != null) {
            messageService.markRead(Long.parseLong(String.valueOf(id)));
        }
        return Result.ok();
    }
}
