package com.tims.ai.controller;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.ai.dto.ChatRequest;
import com.tims.ai.dto.ChatResponseVO;
import com.tims.ai.service.ChatService;
import com.tims.common.api.Result;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.servlet.mvc.method.annotation.SseEmitter;

import java.io.IOException;
import java.util.Map;
import java.util.concurrent.ExecutorService;

/**
 * AI 问答接口（M5，网关 /api/ai/**）：
 * POST /api/ai/chat/stream  SSE 流式（meta/reasoning/delta/usage/error/done）
 * POST /api/ai/chat         同步（测试与降级兜底）
 */
@RestController
@RequestMapping("/api/ai")
public class AiChatController {

    private static final Logger log = LoggerFactory.getLogger(AiChatController.class);

    private final ChatService chatService;
    private final ExecutorService executor;
    private final ObjectMapper mapper;

    public AiChatController(ChatService chatService, ExecutorService aiExecutor, ObjectMapper mapper) {
        this.chatService = chatService;
        this.executor = aiExecutor;
        this.mapper = mapper;
    }

    /** 非流式同步问答 */
    @PostMapping("/chat")
    public Result<ChatResponseVO> chat(@RequestBody ChatRequest request,
                                       @RequestHeader(value = "X-Tenant-Id", required = false) String tenant) {
        return Result.ok(chatService.chatSync(tenantId(tenant), request));
    }

    /** SSE 流式问答（read timeout 120s，与 LLM 配置一致） */
    @PostMapping(value = "/chat/stream", produces = MediaType.TEXT_EVENT_STREAM_VALUE)
    public SseEmitter chatStream(@RequestBody ChatRequest request,
                                 @RequestHeader(value = "X-Tenant-Id", required = false) String tenant) {
        Long tenantId = tenantId(tenant);
        SseEmitter emitter = new SseEmitter(120_000L);
        emitter.onTimeout(() -> log.warn("[ai] SSE 超时（120s）"));
        emitter.onError(e -> log.warn("[ai] SSE 客户端断开: {}", e.getMessage()));

        executor.execute(() -> {
            SseSinkAdapter sink = new SseSinkAdapter(emitter);
            try {
                chatService.chatStream(tenantId, request, sink);
            } catch (ClientGoneException e) {
                log.info("[ai] 客户端提前断开，停止生成");
            } catch (Exception e) {
                log.error("[ai] SSE 处理异常", e);
                sink.error(40201, "AI 服务异常：" + e.getMessage());
            } finally {
                try {
                    emitter.complete();
                } catch (Exception ignore) {
                    // 已完成/已断开时忽略
                }
            }
        });
        return emitter;
    }

    private Long tenantId(String header) {
        try {
            return header == null || header.isBlank() ? 1L : Long.parseLong(header.trim());
        } catch (NumberFormatException e) {
            return 1L;
        }
    }

    /** 客户端断开信号 */
    private static class ClientGoneException extends RuntimeException {
    }

    /** SseEmitter 事件出口 */
    private final class SseSinkAdapter implements ChatService.StreamSink {

        private final SseEmitter emitter;

        SseSinkAdapter(SseEmitter emitter) {
            this.emitter = emitter;
        }

        @Override
        public void meta(Map<String, Object> meta) {
            send("meta", meta);
        }

        @Override
        public void reasoning(String delta) {
            send("reasoning", Map.of("delta", delta));
        }

        @Override
        public void content(String delta) {
            send("delta", Map.of("delta", delta));
        }

        @Override
        public void usage(Map<String, Object> usage) {
            send("usage", usage);
        }

        @Override
        public void error(int code, String message) {
            send("error", Map.of("code", code, "message", message));
        }

        @Override
        public void done() {
            send("done", Map.of("ok", true));
        }

        private void send(String event, Object payload) {
            try {
                String json = mapper.writeValueAsString(payload);
                emitter.send(SseEmitter.event().name(event).data(json, MediaType.TEXT_PLAIN));
            } catch (IOException | IllegalStateException e) {
                throw new ClientGoneException();
            }
        }
    }
}
