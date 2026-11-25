package com.tims.ai.rag;

import com.tims.ai.config.AiProperties;
import com.tims.ai.dto.ChatRequest;
import com.tims.ai.guard.GuardService;
import com.tims.ai.prompt.PromptRegistry;
import com.tims.common.exception.BizException;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * RAG 组装：先检索 Top5 知识（HYBRID/RRF/Milvus 降级由 knowledge 服务负责），
 * 再拼装 system + history + user（参考资料 + 工单上下文 + 问题）。
 */
@Service
public class RagService {

    private final KnowledgeClient knowledgeClient;
    private final OrderClient orderClient;
    private final AiProperties props;
    private final GuardService guard;
    private final PromptRegistry promptRegistry;

    public RagService(KnowledgeClient knowledgeClient, OrderClient orderClient, AiProperties props,
                      GuardService guard, PromptRegistry promptRegistry) {
        this.knowledgeClient = knowledgeClient;
        this.orderClient = orderClient;
        this.props = props;
        this.guard = guard;
        this.promptRegistry = promptRegistry;
    }

    /** RAG 上下文（tier/noKbBasis 仅在 C 档兜底开关打开时用于标识“无库内依据”） */
    public record RagContext(List<KbRef> refs, boolean fallback, boolean unavailable, String mode,
                             long retrievalMs, List<Map<String, String>> messages, String degradedNote,
                             String promptVersion, String tier, String tierReason, boolean noKbBasis,
                             Long ticketId, String ticketNo, String ticketTitle) { }

    public RagContext prepare(Long tenantId, ChatRequest request) {
        if (!StringUtils.hasText(request.getQuestion())) {
            throw new BizException(10400, "question 必填");
        }
        int topK = request.getTopK() == null || request.getTopK() <= 0
                ? props.getTopK() : Math.min(request.getTopK(), 10);

        Map<String, Object> ticket = null;
        if (request.getTicketId() != null) {
            ticket = orderClient.detail(tenantId, request.getTicketId());
        }
        String searchQuery = request.getQuestion();
        if (ticket != null && StringUtils.hasText(asString(ticket.get("title")))) {
            searchQuery = searchQuery + " " + asString(ticket.get("title"));
        }

        KnowledgeClient.SearchOutcome kb = knowledgeClient.search(tenantId, searchQuery, topK);
        String degradedNote = null;
        if (kb.unavailable()) {
            degradedNote = "【知识库检索降级】知识库服务暂不可用，本次回答未引用知识条目。";
        } else if (kb.fallback()) {
            degradedNote = "【知识库检索降级】向量检索不可用，已降级为关键词检索。";
        }
        // C 档兜底：仅在开关打开且检索正常返回 C 档时生效；KB 不可用不走该分支
        boolean fallbackEnabled = props.getFallback() != null && props.getFallback().isEnabled();
        boolean noKbBasis = fallbackEnabled && !kb.unavailable() && "C".equalsIgnoreCase(kb.tier());

        List<Map<String, String>> messages = new ArrayList<>();
        PromptRegistry.Active prompt = promptRegistry.active(tenantId, "CHAT");
        messages.add(msg("system", prompt.content()));
        if (request.getHistory() != null) {
            int from = Math.max(0, request.getHistory().size() - 6);
            for (ChatRequest.HistoryMsg h : request.getHistory().subList(from, request.getHistory().size())) {
                if (StringUtils.hasText(h.getRole()) && StringUtils.hasText(h.getContent())
                        && ("user".equals(h.getRole()) || "assistant".equals(h.getRole()))) {
                    messages.add(msg(h.getRole(), h.getContent()));
                }
            }
        }
        messages.add(msg("user", guard.mask(
                buildUserPrompt(request.getQuestion(), kb, ticket, degradedNote, noKbBasis))));
        String ticketNo = ticket == null ? null : asString(ticket.get("ticketNo"));
        String ticketTitle = ticket == null ? null : asString(ticket.get("title"));
        return new RagContext(kb.refs(), kb.fallback(), kb.unavailable(), kb.mode(),
                kb.elapsedMs(), messages, degradedNote, prompt.version(),
                kb.tier(), kb.tierReason(), noKbBasis, request.getTicketId(),
                StringUtils.hasText(ticketNo) ? ticketNo : null,
                StringUtils.hasText(ticketTitle) ? ticketTitle.trim() : null);
    }

    private String buildUserPrompt(String question, KnowledgeClient.SearchOutcome kb,
                                   Map<String, Object> ticket, String degradedNote, boolean noKbBasis) {
        StringBuilder sb = new StringBuilder();
        if (degradedNote != null) {
            sb.append("【系统提示】").append(degradedNote).append('\n');
        }
        if (noKbBasis) {
            sb.append("【兜底模式】知识库门控判定为 C 档，本次没有可引用的知识条目。")
                    .append("请基于通用维修经验给出可操作的排查建议；禁止编造知识库引用或工单编号，")
                    .append("回答中不得声称有知识库依据。\n");
        }
        sb.append("【知识库参考】\n");
        if (kb.refs().isEmpty()) {
            sb.append("（无命中知识条目）\n");
        } else {
            for (int i = 0; i < kb.refs().size(); i++) {
                KbRef ref = kb.refs().get(i);
                sb.append('[').append('K').append(i + 1).append("] 标题：").append(ref.title()).append('\n');
                if (StringUtils.hasText(ref.summary())) {
                    sb.append("摘要：").append(ref.summary()).append('\n');
                }
                String content = i < kb.contents().size() ? kb.contents().get(i) : "";
                if (StringUtils.hasText(content)) {
                    sb.append("正文：").append(content).append('\n');
                }
                if (StringUtils.hasText(ref.deviceType())) {
                    sb.append("适用设备：").append(ref.deviceType()).append('\n');
                }
                sb.append('\n');
            }
        }
        if (ticket != null) {
            sb.append("【当前工单】\n");
            sb.append("编号：").append(asString(ticket.get("ticketNo"))).append('\n');
            sb.append("标题：").append(asString(ticket.get("title"))).append('\n');
            sb.append("状态：").append(asString(ticket.get("status"))).append('\n');
            sb.append("设备类型：").append(asString(ticket.get("deviceType"))).append('\n');
            sb.append("紧急度：").append(asString(ticket.get("urgency"))).append('\n');
            sb.append("描述：").append(truncate(asString(ticket.get("description")), 800)).append('\n');
            if (StringUtils.hasText(asString(ticket.get("resolveNote")))) {
                sb.append("处理说明：").append(truncate(asString(ticket.get("resolveNote")), 400)).append('\n');
            }
            sb.append('\n');
        }
        sb.append("【用户问题】\n").append(question);
        return sb.toString();
    }

    private static Map<String, String> msg(String role, String content) {
        Map<String, String> m = new LinkedHashMap<>();
        m.put("role", role);
        m.put("content", content);
        return m;
    }

    private static String asString(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static String truncate(String s, int max) {
        return s.length() <= max ? s : s.substring(0, max) + "...";
    }
}
