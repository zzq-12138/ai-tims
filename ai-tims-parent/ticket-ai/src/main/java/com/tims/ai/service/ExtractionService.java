package com.tims.ai.service;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.ai.config.AiProperties;
import com.tims.ai.dto.ExtractRequest;
import com.tims.ai.dto.ExtractResult;
import com.tims.ai.llm.LlmException;
import com.tims.ai.usage.AiCallLog;
import com.tims.ai.usage.AiUsageService;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.SystemMessage;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.chat.metadata.Usage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.prompt.Prompt;
import org.springframework.ai.openai.OpenAiChatModel;
import org.springframework.ai.openai.OpenAiChatOptions;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.List;

/**
 * M6 工单知识抽取：已关闭工单 → 结构化知识（模型名可配）。
 * M6.1 默认 glm-5.3-flash（S3 口径）；S1 基线用 glm-4-flash 的 316 条现成数据，同标注集对比。
 * - 只负责 LLM 调用与结构化解析，不落库、不做去重（落库/审核/合并归 ticket-knowledge）；
 * - 每次调用落 ai_call_log（scene=EXTRACT），供配额观测；
 * - 解析失败/模型不可用抛 LlmException，由 ticket-knowledge 落“待人工补录”记录，不阻塞工单关闭。
 */
@Service
public class ExtractionService {

    private static final Logger log = LoggerFactory.getLogger(ExtractionService.class);

    private static final String SYSTEM_PROMPT = """
            你是制造业设备维修知识工程师。请从已关闭工单中提炼可复用的维修知识。
            严格只输出一个 JSON 对象（禁止 markdown 代码块、禁止前后解释文字），字段如下：
            {
              "title": "不超过30字，包含设备类型与故障关键词",
              "deviceType": "适用设备类型，尽量沿用工单设备类型",
              "faultPhenomenon": "故障现象的凝练描述",
              "troubleshootSteps": ["排查步骤1", "排查步骤2"],
              "solutionSteps": ["解决步骤1", "解决步骤2"],
              "tags": ["3-6个短标签，含设备类型与关键部件"],
              "keyPoints": ["关键要点1", "关键要点2"]
            }
            只使用工单中出现的信息；信息不足时可按通用维修常识简短补充，禁止编造具体参数与备件型号。
            """;

    private final OpenAiChatModel chatModel;
    private final AiProperties props;
    private final AiUsageService usageService;
    private final ObjectMapper mapper = new ObjectMapper();

    public ExtractionService(OpenAiChatModel chatModel, AiProperties props, AiUsageService usageService) {
        this.chatModel = chatModel;
        this.props = props;
        this.usageService = usageService;
    }

    public ExtractResult extract(Long tenantId, ExtractRequest req) {
        long t0 = System.currentTimeMillis();
        String model = props.getExtractModel();
        try {
            List<Message> messages = List.of(
                    new SystemMessage(SYSTEM_PROMPT),
                    new UserMessage(buildUserPrompt(req)));
            OpenAiChatOptions options = OpenAiChatOptions.builder()
                    .model(model)
                    .temperature(0.2)
                    .maxTokens(props.getExtractMaxTokens())
                    .build();
            ChatResponse resp = chatModel.call(new Prompt(messages, options));
            String text = resp.getResult() == null ? "" : resp.getResult().getOutput().getText();
            Usage u = resp.getMetadata() == null ? null : resp.getMetadata().getUsage();
            int prompt = u == null || u.getPromptTokens() == null ? 0 : u.getPromptTokens();
            int completion = u == null || u.getCompletionTokens() == null ? 0 : u.getCompletionTokens();

            ExtractResult result = parse(text);
            if (!StringUtils.hasText(result.getTitle())) {
                result.setTitle(StringUtils.hasText(req.getTitle()) ? req.getTitle() : req.getTicketNo());
            }
            if (!StringUtils.hasText(result.getDeviceType())) {
                result.setDeviceType(req.getDeviceType());
            }
            result.setModel(model);
            result.setPromptTokens(prompt);
            result.setCompletionTokens(completion);
            result.setTotalTokens(prompt + completion);
            result.setLatencyMs(System.currentTimeMillis() - t0);

            AiCallLog row = new AiCallLog();
            row.setTenantId(tenantId == null ? 1L : tenantId);
            row.setScene("EXTRACT");
            row.setModel(model);
            row.setPromptTokens(prompt);
            row.setCompletionTokens(completion);
            row.setTotalTokens(prompt + completion);
            row.setLatencyMs(result.getLatencyMs());
            row.setStatus("SUCCESS");
            row.setDegraded(false);
            row.setRefCount(0);
            usageService.record(row);
            log.info("[extract] ticket={} model={} tokens={}/{} {}ms",
                    req.getTicketNo(), model, prompt, completion, result.getLatencyMs());
            return result;
        } catch (Exception e) {
            long cost = System.currentTimeMillis() - t0;
            AiCallLog row = new AiCallLog();
            row.setTenantId(tenantId == null ? 1L : tenantId);
            row.setScene("EXTRACT");
            row.setModel(model);
            row.setLatencyMs(cost);
            row.setStatus("ERROR");
            row.setDegraded(true);
            row.setErrorMsg(truncate(e.getMessage(), 250));
            usageService.record(row);
            log.error("[extract] 失败 ticket={} model={} {}ms: {}", req.getTicketNo(), model, cost, e.getMessage());
            if (e instanceof LlmException le) {
                throw le;
            }
            throw new LlmException(40203, "知识抽取失败：" + e.getMessage());
        }
    }

    private String buildUserPrompt(ExtractRequest req) {
        StringBuilder sb = new StringBuilder(512);
        sb.append("工单编号：").append(nullToEmpty(req.getTicketNo())).append('\n');
        sb.append("工单标题：").append(nullToEmpty(req.getTitle())).append('\n');
        sb.append("设备类型：").append(nullToEmpty(req.getDeviceType())).append('\n');
        sb.append("故障描述：").append(nullToEmpty(req.getDescription())).append('\n');
        sb.append("解决说明：").append(nullToEmpty(req.getResolveNote())).append('\n');
        if (req.getFlows() != null && !req.getFlows().isEmpty()) {
            sb.append("流转记录：\n");
            for (String f : req.getFlows()) {
                if (StringUtils.hasText(f)) {
                    sb.append("- ").append(f).append('\n');
                }
            }
        }
        if (req.getComments() != null && !req.getComments().isEmpty()) {
            sb.append("沟通记录：\n");
            for (String c : req.getComments()) {
                if (StringUtils.hasText(c)) {
                    sb.append("- ").append(c).append('\n');
                }
            }
        }
        return sb.toString();
    }

    /** 解析模型输出：兼容 markdown 代码块/前后解释，字段缺失时降级为空 */
    private ExtractResult parse(String text) {
        if (!StringUtils.hasText(text)) {
            throw new LlmException(40203, "知识抽取返回为空");
        }
        int start = text.indexOf('{');
        int end = text.lastIndexOf('}');
        if (start < 0 || end <= start) {
            throw new LlmException(40203, "知识抽取返回不含 JSON");
        }
        try {
            JsonNode node = mapper.readTree(text.substring(start, end + 1));
            ExtractResult r = new ExtractResult();
            r.setTitle(node.path("title").asText(""));
            r.setDeviceType(node.path("deviceType").asText(""));
            r.setFaultPhenomenon(node.path("faultPhenomenon").asText(""));
            r.setTroubleshootSteps(listText(node.get("troubleshootSteps")));
            r.setSolutionSteps(listText(node.get("solutionSteps")));
            r.setKeyPoints(listText(node.get("keyPoints")));
            r.setTags(listTags(node.get("tags")));
            return r;
        } catch (Exception e) {
            throw new LlmException(40203, "知识抽取 JSON 解析失败：" + e.getMessage());
        }
    }

    /** 数组 → 编号文本；字符串原样返回 */
    private String listText(JsonNode node) {
        if (node == null || node.isNull()) {
            return "";
        }
        if (node.isArray()) {
            StringBuilder sb = new StringBuilder();
            int i = 1;
            for (JsonNode item : node) {
                String s = item.asText("").trim();
                if (!s.isEmpty()) {
                    sb.append(i++).append(". ").append(s).append('\n');
                }
            }
            return sb.toString().trim();
        }
        return node.asText("").trim();
    }

    private List<String> listTags(JsonNode node) {
        List<String> tags = new ArrayList<>();
        if (node == null || node.isNull()) {
            return tags;
        }
        if (node.isArray()) {
            for (JsonNode item : node) {
                String s = item.asText("").trim();
                if (!s.isEmpty() && tags.size() < 8 && !tags.contains(s)) {
                    tags.add(s);
                }
            }
        } else {
            String s = node.asText("").trim();
            if (!s.isEmpty()) {
                for (String part : s.split("[,，]")) {
                    String t = part.trim();
                    if (!t.isEmpty() && tags.size() < 8 && !tags.contains(t)) {
                        tags.add(t);
                    }
                }
            }
        }
        return tags;
    }

    private static String nullToEmpty(String s) {
        return s == null ? "" : s;
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }
}
