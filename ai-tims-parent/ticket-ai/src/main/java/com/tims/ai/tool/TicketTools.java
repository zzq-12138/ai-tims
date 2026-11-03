package com.tims.ai.tool;

import com.tims.ai.rag.KbRef;
import com.tims.ai.rag.KnowledgeClient;
import com.tims.ai.rag.OrderClient;
import com.tims.ai.util.RequestUtils;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;
import org.springframework.util.StringUtils;

import java.util.List;
import java.util.Map;

/**
 * 工单助手工具集（严格 3 个，避免工具过多导致选错/推理变慢）：
 * 1) query_ticket_status  查工单状态
 * 2) search_knowledge     检索知识库
 * 3) ticket_statistics    取工单统计
 * 每次调用都写日志（工具名/参数/耗时），并汇入 ai_call_log(scene=AGENT_TOOL)。
 */
@Component
public class TicketTools {

    private static final Logger log = LoggerFactory.getLogger(TicketTools.class);

    private final OrderClient orderClient;
    private final KnowledgeClient knowledgeClient;

    public TicketTools(OrderClient orderClient, KnowledgeClient knowledgeClient) {
        this.orderClient = orderClient;
        this.knowledgeClient = knowledgeClient;
    }

    @Tool(name = "query_ticket_status",
            description = "查询工单进度/状态，必须调用。用户消息里出现工单ID（纯数字）、工单编号（WO 开头）或询问某工单处理到哪一步时，直接调用本工具；keyword 填用户给出的编号/ID/标题关键词，不要反问用户。")
    public String queryTicketStatus(
            @ToolParam(description = "工单ID（纯数字）或工单编号/标题关键词，例如 2117xxx 或 贴片机抛料") String keyword) {
        long t0 = System.currentTimeMillis();
        String args = "keyword=" + keyword;
        String result;
        boolean degraded = false;
        try {
            Long tenant = RequestUtils.tenantId();
            if (StringUtils.hasText(keyword) && keyword.trim().matches("\\d{6,}")) {
                Map<String, Object> ticket = orderClient.detail(tenant, Long.parseLong(keyword.trim()));
                result = ticket == null ? "未找到该工单（ID=" + keyword + "）。" : formatTicket(ticket);
            } else {
                List<Map<String, Object>> list = orderClient.search(tenant, keyword, 5);
                if (list.isEmpty()) {
                    result = "未检索到匹配工单（关键词=" + keyword + "）。";
                } else {
                    StringBuilder sb = new StringBuilder("匹配到 ").append(list.size()).append(" 条工单：\n");
                    for (Map<String, Object> t : list) {
                        sb.append("- ").append(formatTicketLine(t)).append('\n');
                    }
                    result = sb.toString();
                }
            }
        } catch (Exception e) {
            degraded = true;
            result = "工单查询失败：" + e.getMessage();
            log.warn("[tool] query_ticket_status 失败 args={}: {}", args, e.getMessage());
        }
        long ms = System.currentTimeMillis() - t0;
        ToolCallRecorder.add(new ToolCallRecorder.Record("query_ticket_status", args, ms,
                degraded ? "FAIL" : "OK", truncate(result, 120), degraded));
        log.info("[tool] query_ticket_status args={} elapsed={}ms result={}", args, ms, truncate(result, 80));
        return result;
    }

    @Tool(name = "search_knowledge",
            description = "检索设备维修知识库（向量+关键词混合检索）。用户询问故障处理、SOP、参数阈值、历史经验时调用。")
    public String searchKnowledge(
            @ToolParam(description = "检索关键词或故障描述，尽量包含设备类型与现象") String query,
            @ToolParam(description = "返回条数，默认5，最大10", required = false) Integer topK) {
        long t0 = System.currentTimeMillis();
        int k = topK == null ? 5 : Math.max(1, Math.min(topK, 10));
        String args = "query=" + query + ", topK=" + k;
        String result;
        boolean degraded = false;
        try {
            KnowledgeClient.SearchOutcome outcome = knowledgeClient.search(RequestUtils.tenantId(), query, k);
            degraded = outcome.fallback();
            if (outcome.unavailable()) {
                result = "知识库服务暂不可用，未获取到知识条目。";
            } else if (outcome.refs().isEmpty()) {
                result = "知识库无匹配条目。";
            } else {
                StringBuilder sb = new StringBuilder();
                if (outcome.fallback()) {
                    sb.append("（知识库检索降级：向量检索不可用，已降级为关键词检索）\n");
                }
                List<KbRef> refs = outcome.refs();
                for (int i = 0; i < refs.size(); i++) {
                    KbRef r = refs.get(i);
                    sb.append("[K").append(i + 1).append("] ").append(r.title());
                    if (StringUtils.hasText(r.deviceType())) {
                        sb.append("（设备：").append(r.deviceType()).append("）");
                    }
                    if (StringUtils.hasText(r.summary())) {
                        sb.append("：").append(r.summary());
                    }
                    sb.append('\n');
                }
                result = sb.toString();
            }
        } catch (Exception e) {
            degraded = true;
            result = "知识库检索失败：" + e.getMessage();
            log.warn("[tool] search_knowledge 失败 args={}: {}", args, e.getMessage());
        }
        long ms = System.currentTimeMillis() - t0;
        ToolCallRecorder.add(new ToolCallRecorder.Record("search_knowledge", args, ms,
                degraded ? "FAIL" : "OK", truncate(result, 120), degraded));
        log.info("[tool] search_knowledge args={} elapsed={}ms degraded={}", args, ms, degraded);
        return result;
    }

    @Tool(name = "ticket_statistics",
            description = "查询当前租户工单统计概览（待办数、今日新建、关闭率、AI采纳率）。用户问“今天工单量/待办多少/关闭率”时调用。")
    public String ticketStatistics() {
        long t0 = System.currentTimeMillis();
        String result;
        boolean degraded = false;
        try {
            Map<String, Object> data = orderClient.overview(RequestUtils.tenantId());
            if (data == null) {
                degraded = true;
                result = "统计服务暂不可用。";
            } else {
                result = String.format("待办工单 %s 条；今日新建 %s 条；关闭率 %.1f%%；AI采纳率 %.1f%%。",
                        data.get("todoCount"),
                        data.get("todayCreated"),
                        asRate(data.get("closedRate")), asRate(data.get("adoptionRate")));
            }
        } catch (Exception e) {
            degraded = true;
            result = "统计查询失败：" + e.getMessage();
            log.warn("[tool] ticket_statistics 失败: {}", e.getMessage());
        }
        long ms = System.currentTimeMillis() - t0;
        ToolCallRecorder.add(new ToolCallRecorder.Record("ticket_statistics", "{}", ms,
                degraded ? "FAIL" : "OK", truncate(result, 120), degraded));
        log.info("[tool] ticket_statistics elapsed={}ms result={}", ms, truncate(result, 80));
        return result;
    }

    private static double asRate(Object o) {
        return o instanceof Number n ? n.doubleValue() * 100 : 0;
    }

    private static String formatTicket(Map<String, Object> t) {
        StringBuilder sb = new StringBuilder();
        sb.append("工单 ").append(asString(t.get("ticketNo"))).append("（ID ").append(asString(t.get("id"))).append("）\n");
        sb.append("标题：").append(asString(t.get("title"))).append('\n');
        sb.append("状态：").append(statusLabel(asString(t.get("status")))).append('\n');
        sb.append("设备类型：").append(asString(t.get("deviceType"))).append('\n');
        sb.append("紧急度：").append(asString(t.get("urgency"))).append('\n');
        sb.append("处理人：").append(asString(t.get("handlerName"))).append('\n');
        sb.append("创建时间：").append(asString(t.get("createTime"))).append('\n');
        sb.append("问题描述：").append(truncate(asString(t.get("description")), 300));
        return sb.toString();
    }

    private static String formatTicketLine(Map<String, Object> t) {
        return asString(t.get("ticketNo")) + " | " + statusLabel(asString(t.get("status")))
                + " | " + asString(t.get("deviceType")) + " | " + asString(t.get("title"));
    }

    private static String statusLabel(String code) {
        return switch (code == null ? "" : code) {
            case "DRAFT" -> "草稿";
            case "SUBMITTED" -> "待受理";
            case "ACCEPTED" -> "已受理";
            case "PROCESSING" -> "处理中";
            case "WAIT_VERIFY" -> "待验证";
            case "RESOLVED" -> "已解决";
            case "CLOSED" -> "已关闭";
            case "SUSPENDED" -> "已挂起";
            default -> code;
        };
    }

    private static String asString(Object o) {
        return o == null ? "" : String.valueOf(o);
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return "";
        }
        String one = s.replaceAll("\\s+", " ").trim();
        return one.length() <= max ? one : one.substring(0, max) + "...";
    }
}
