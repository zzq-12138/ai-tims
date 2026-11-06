package com.tims.ai.usage;

import com.tims.common.api.Result;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.time.LocalDateTime;
import java.util.Map;

/**
 * 内部用量上报（M6）：ticket-knowledge 的 embedding 调用成功后异步回传，落到 ai_call_log。
 * <p>
 * 仅内网调用（knowledge → 8104 直连，不经网关）；落库失败只记日志，不影响 knowledge 业务。
 * 生产环境应加内网 ACL 或共享密钥，演示环境从简（与现有演示级信任边界一致）。
 */
@RestController
@RequestMapping("/api/ai/usage")
public class UsageRecordController {

    private static final Logger log = LoggerFactory.getLogger(UsageRecordController.class);

    private final AiUsageService usageService;

    public UsageRecordController(AiUsageService usageService) {
        this.usageService = usageService;
    }

    @PostMapping("/record")
    public Result<Boolean> record(@RequestBody Map<String, Object> body) {
        AiCallLog row = new AiCallLog();
        row.setTenantId(longOf(body.get("tenantId"), 1L));
        row.setScene(str(body.get("scene"), "EMBED"));
        row.setModel(str(body.get("model"), "embedding-3"));
        row.setPromptTokens(longOf(body.get("promptTokens"), 0L).intValue());
        row.setCompletionTokens(longOf(body.get("completionTokens"), 0L).intValue());
        row.setTotalTokens((int) (longOf(body.get("promptTokens"), 0L) + longOf(body.get("completionTokens"), 0L)));
        row.setLatencyMs(longOf(body.get("latencyMs"), 0L));
        row.setStatus("SUCCESS");
        row.setDegraded(false);
        row.setCreateTime(LocalDateTime.now());
        usageService.record(row);
        log.info("[usage] 上报 {} model={} tokens={} latency={}ms",
                row.getScene(), row.getModel(), row.getTotalTokens(), row.getLatencyMs());
        return Result.ok(true);
    }

    private String str(Object v, String def) {
        return v == null || String.valueOf(v).isBlank() ? def : String.valueOf(v);
    }

    private Long longOf(Object v, Long def) {
        if (v == null) {
            return def;
        }
        try {
            return Long.parseLong(String.valueOf(v).trim());
        } catch (NumberFormatException e) {
            return def;
        }
    }
}
