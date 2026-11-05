package com.tims.ai.controller;

import com.tims.ai.dto.AssistantRequest;
import com.tims.ai.dto.AssistantVO;
import com.tims.ai.service.AssistantService;
import com.tims.ai.util.CurrentUser;
import com.tims.common.api.Result;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * 工单助手接口（M5）：POST /api/ai/assistant
 * 同步返回答案 + 工具调用明细（name/args/elapsedMs），工具明细同时落 ai_call_log。
 */
@RestController
@RequestMapping("/api/ai")
public class AssistantController {

    private final AssistantService assistantService;

    public AssistantController(AssistantService assistantService) {
        this.assistantService = assistantService;
    }

    @PostMapping("/assistant")
    public Result<AssistantVO> assistant(@RequestBody AssistantRequest request) {
        return Result.ok(assistantService.chat(CurrentUser.tenantId(), CurrentUser.id(), request));
    }
}
