package com.tims.push.service;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.push.ws.WsSessionRegistry;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 推送管线（M4 核心，降级矩阵全部落地）：
 *
 * ticket.created 事件 →
 *   ① 埋点行初始化（t_created/t_event_sent 来自事件体；MQ 降级路径 degraded|=2）
 *   ② 调 kb HYBRID 检索组装知识卡片
 *      - 正常：items 透传；kb 返回 fallback=true（Milvus 不可用已降关键词）→ degraded|=1 透传
 *      - kb 全不可用：items=[] + notice 明确提示（degraded|=4），绝不静默失败
 *   ③ 扇出在线坐席（WS）；离线坐席落站内消息表（上线/重连补推）
 *   ④ 埋点补 t_retrieve_done / t_push_sent / e2e_ms
 */
@Service
public class PushPipeline {

    private static final Logger log = LoggerFactory.getLogger(PushPipeline.class);

    public static final int DEG_KB_FALLBACK = 1; // Milvus 不可用 → 纯关键词兜底
    public static final int DEG_MQ = 2;          // MQ 不可用 → HTTP 直调本地线程池
    public static final int DEG_KB_DOWN = 4;     // kb 全不可用 → 空卡片

    private static final DateTimeFormatter MS = DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS");

    private final KnowledgeClient knowledgeClient;
    private final WsSessionRegistry sessionRegistry;
    private final MessageService messageService;
    private final LatencyService latencyService;
    private final ObjectMapper objectMapper = new ObjectMapper();

    public PushPipeline(KnowledgeClient knowledgeClient,
                        WsSessionRegistry sessionRegistry,
                        MessageService messageService,
                        LatencyService latencyService) {
        this.knowledgeClient = knowledgeClient;
        this.sessionRegistry = sessionRegistry;
        this.messageService = messageService;
        this.latencyService = latencyService;
    }

    /** 事件入口（MQ 消费与 HTTP 降级共用）；degradedMq=true 表示事件走了降级通道 */
    public void handleEvent(Map<String, Object> event, boolean degradedMq) {
        String eventType = String.valueOf(event.getOrDefault("eventType", ""));
        long tenantId = toLong(event.get("tenantId"), 1L);
        com.tims.push.config.PushTenantContext.set(tenantId);
        try {
            if ("ticket.created".equals(eventType)) {
                handleCreated(event, tenantId, degradedMq);
            } else if ("ticket.closed".equals(eventType)) {
                handleClosed(event, tenantId);
            } else {
                log.warn("未知事件类型 {}，忽略", eventType);
            }
        } finally {
            com.tims.push.config.PushTenantContext.clear();
        }
    }

    private void handleCreated(Map<String, Object> event, long tenantId, boolean degradedMq) {
        long ticketId = toLong(event.get("ticketId"), 0L);
        String ticketNo = str(event.get("ticketNo"));
        String deviceType = str(event.get("deviceType"));
        String title = str(event.get("title"));
        String description = str(event.get("description"));
        Long handlerId = event.get("handlerId") == null ? null : toLong(event.get("handlerId"), 0L);
        LocalDateTime tCreated = parse(event.get("tCreated"));
        LocalDateTime tEventSent = parse(event.get("tEventSent"));
        if (tCreated == null) tCreated = LocalDateTime.now();
        if (tEventSent == null) tEventSent = LocalDateTime.now();
        int degraded = degradedMq ? DEG_MQ : 0;

        // ① 埋点初始化
        try {
            latencyService.initRow(ticketId, ticketNo, deviceType, tCreated, tEventSent, degraded);
        } catch (Exception e) {
            log.warn("埋点初始化失败 ticketId={}: {}", ticketId, e.getMessage());
        }

        // ② 检索组卡（HYBRID，Top5）
        String query = ((title == null ? "" : title) + " " + (deviceType == null ? "" : deviceType)
                + " " + firstClause(description)).trim();
        if (query.isBlank()) query = ticketNo;
        KnowledgeClient.KbResult kb = knowledgeClient.searchHybrid(tenantId, query, 5);
        if (kb.fallback() && kb.available()) degraded |= DEG_KB_FALLBACK;
        if (!kb.available()) degraded |= DEG_KB_DOWN;
        LocalDateTime tRetrieveDone = LocalDateTime.now();

        Map<String, Object> card = new LinkedHashMap<>();
        card.put("ticketId", ticketId);
        card.put("ticketNo", ticketNo);
        card.put("title", title);
        card.put("deviceType", deviceType);
        card.put("urgency", event.get("urgency"));
        card.put("createTime", tCreated.format(MS));
        card.put("items", slimItems(kb.items()));
        card.put("degraded", degraded != 0);
        card.put("degradedBits", degraded);
        if (!kb.available()) {
            card.put("notice", "知识检索服务暂不可用，本卡片无推荐知识；请稍后在知识库手动检索，或联系管理员。");
        } else if (kb.fallback()) {
            card.put("notice", "向量检索引擎不可用，已自动降级为关键词检索。");
        } else {
            card.put("notice", null);
        }
        String cardJson = toJson(card);

        // ③ 扇出：在线坐席 WS 直推；离线坐席（含 handler）落站内消息补推
        LocalDateTime tPushSent = LocalDateTime.now();
        int online = 0;
        List<Long> offlineTargets = new ArrayList<>();
        if (handlerId != null && handlerId > 0) offlineTargets.add(handlerId);
        for (Map<String, Object> u : sessionRegistry.listOnline()) {
            if (toLong(u.get("tenantId"), 1L) != tenantId) continue;
            Long uid = toLong(u.get("userId"), 0L);
            if (sessionRegistry.sendToUser(uid, toJson(Map.of("type", "CARD", "data", card)))) {
                online++;
                offlineTargets.remove(uid);
                tPushSent = LocalDateTime.now();
            }
        }
        for (Long uid : offlineTargets) {
            try {
                messageService.saveOffline(tenantId, ticketId, uid,
                        "新工单知识卡片：" + (title == null ? ticketNo : title), cardJson);
            } catch (Exception e) {
                log.warn("站内消息落库失败 ticketId={} userId={}: {}", ticketId, uid, e.getMessage());
            }
        }

        // ④ 埋点补全
        try {
            latencyService.completeRow(ticketId, tRetrieveDone, tPushSent, degraded);
        } catch (Exception e) {
            log.warn("埋点补全失败 ticketId={}: {}", ticketId, e.getMessage());
        }
        log.info("[推送完成] ticketId={} no={} online={} offline={} degraded={} query={}",
                ticketId, ticketNo, online, offlineTargets.size(), degraded, query);
    }

    /** ticket.closed：在线坐席轻通知（不做埋点，不落站内信） */
    private void handleClosed(Map<String, Object> event, long tenantId) {
        Map<String, Object> notify = Map.of("type", "TICKET_CLOSED", "data", event);
        int n = 0;
        for (Map<String, Object> u : sessionRegistry.listOnline()) {
            if (toLong(u.get("tenantId"), 1L) != tenantId) continue;
            if (sessionRegistry.sendToUser(toLong(u.get("userId"), 0L), toJson(notify))) n++;
        }
        log.info("[关闭通知] ticketId={} 通知在线坐席 {} 人", event.get("ticketId"), n);
    }

    /** 卡片条目瘦身：content 截断，保留检索展示所需字段 */
    private List<Map<String, Object>> slimItems(List<Map<String, Object>> items) {
        List<Map<String, Object>> out = new ArrayList<>();
        for (Map<String, Object> it : items) {
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("id", it.get("id"));
            m.put("title", it.get("title"));
            m.put("summary", it.get("summary"));
            Object content = it.get("content");
            if (content instanceof String s && s.length() > 200) {
                content = s.substring(0, 200) + "…";
            }
            m.put("content", content);
            m.put("tags", it.get("tags"));
            m.put("applyDeviceType", it.get("applyDeviceType"));
            m.put("score", it.get("score"));
            out.add(m);
        }
        return out;
    }

    private String firstClause(String s) {
        if (s == null) return "";
        return s.length() > 60 ? s.substring(0, 60) : s;
    }

    private LocalDateTime parse(Object o) {
        if (o == null) return null;
        try {
            return LocalDateTime.parse(String.valueOf(o).replace(" ", "T").substring(0, 23),
                    DateTimeFormatter.ofPattern("yyyy-MM-dd'T'HH:mm:ss.SSS"));
        } catch (Exception e) {
            try {
                return LocalDateTime.parse(String.valueOf(o).replace(" ", "T"));
            } catch (Exception e2) {
                return null;
            }
        }
    }

    private long toLong(Object o, long dft) {
        if (o instanceof Number n) return n.longValue();
        try {
            return Long.parseLong(String.valueOf(o));
        } catch (Exception e) {
            return dft;
        }
    }

    private String str(Object o) {
        return o == null ? null : String.valueOf(o);
    }

    private String toJson(Object o) {
        try {
            return objectMapper.writeValueAsString(o);
        } catch (Exception e) {
            return "{}";
        }
    }
}
