package com.tims.push.controller;

import com.tims.common.api.Result;
import com.tims.common.enums.ErrorCode;
import com.tims.common.exception.BizException;
import com.tims.push.config.PushInfraConfig;
import com.tims.push.service.PushPipeline;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Qualifier;
import org.springframework.http.HttpHeaders;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Map;
import java.util.concurrent.ExecutorService;

/**
 * 降级事件入口（M4）：MQ 不可用时 order HTTP 直调（降级矩阵第②级）。
 * 网关侧 /api/push/internal/** 需登录态，且本接口校验 X-Internal-Token 共享密钥双重防护。
 * 收到即提交本地线程池（pushExecutor）执行推送管线，degraded|=2（MQ 降级）。
 */
@RestController
@RequestMapping("/api/push/internal")
public class InternalEventController {

    private static final Logger log = LoggerFactory.getLogger(InternalEventController.class);

    private final PushPipeline pipeline;
    private final PushInfraConfig infra;
    private final ExecutorService pushExecutor;

    public InternalEventController(PushPipeline pipeline,
                                   PushInfraConfig infra,
                                   @Qualifier("pushExecutor") ExecutorService pushExecutor) {
        this.pipeline = pipeline;
        this.infra = infra;
        this.pushExecutor = pushExecutor;
    }

    @PostMapping("/event")
    public Result<Void> receive(@RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String auth,
                                @RequestHeader(value = "X-Internal-Token", required = false) String token,
                                @RequestBody Map<String, Object> event) {
        if (token == null || !token.equals(infra.internalToken())) {
            throw new BizException(ErrorCode.FORBIDDEN, "内部接口密钥校验失败");
        }
        log.warn("[HTTP降级接收] {} ticketId={}（MQ 不可用，本地线程池直连）",
                event.get("eventType"), event.get("ticketId"));
        pushExecutor.submit(() -> pipeline.handleEvent(event, true));
        return Result.ok(null);
    }
}
