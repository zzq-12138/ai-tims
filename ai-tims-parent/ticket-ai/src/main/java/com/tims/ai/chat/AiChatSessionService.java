package com.tims.ai.chat;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.tims.common.exception.BizException;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Set;

/**
 * AI 会话持久化（M6 问题8）。
 * 隔离：所有读写都带 tenant_id + user_id 条件，越权访问按“不存在”处理。
 * 上下文：会话历史从库里取最近 N 条，前端无需回传全部历史（刷新/切会话/换设备一致）。
 */
@Service
public class AiChatSessionService {

    public static final String DEFAULT_TITLE = "新会话";
    private static final int HISTORY_WINDOW = 10;

    /**
     * 只读工具白名单：不在这份名单里的工具一律按“有副作用”处理。
     * 依据是已落库的 tool_calls 名称，不做关键词猜测；新增写工具时无需改这里，默认就会走确认。
     */
    private static final Set<String> READ_ONLY_TOOLS = Set.of(
            "query_ticket_status", "search_knowledge", "ticket_statistics",
            "query_ticket_detail", "list_tickets", "search_tickets"
    );

    private final AiChatSessionMapper sessionMapper;
    private final AiChatMessageMapper messageMapper;
    private final ObjectMapper objectMapper;

    public AiChatSessionService(AiChatSessionMapper sessionMapper, AiChatMessageMapper messageMapper,
                                ObjectMapper objectMapper) {
        this.sessionMapper = sessionMapper;
        this.messageMapper = messageMapper;
        this.objectMapper = objectMapper;
    }

    public AiChatSession create(Long tenantId, Long userId, String title) {
        requireUser(userId);
        AiChatSession s = new AiChatSession();
        s.setTenantId(tenantId == null ? 1L : tenantId);
        s.setUserId(userId);
        s.setTitle(StringUtils.hasText(title) ? trimTitle(title) : DEFAULT_TITLE);
        s.setCreateTime(LocalDateTime.now());
        s.setUpdateTime(s.getCreateTime());
        s.setDeleted(0);
        sessionMapper.insert(s);
        return s;
    }

    public List<AiChatSession> list(Long tenantId, Long userId) {
        requireUser(userId);
        LambdaQueryWrapper<AiChatSession> q = new LambdaQueryWrapper<>();
        q.eq(AiChatSession::getTenantId, tenantId == null ? 1L : tenantId)
                .eq(AiChatSession::getUserId, userId)
                .eq(AiChatSession::getDeleted, 0)
                .orderByDesc(AiChatSession::getUpdateTime)
                .orderByDesc(AiChatSession::getId);
        return sessionMapper.selectList(q);
    }

    /** 取会话并校验归属，越权/不存在统一抛 10404 */
    public AiChatSession require(Long tenantId, Long userId, Long sessionId) {
        requireUser(userId);
        if (sessionId == null) {
            throw new BizException(10404, "会话不存在");
        }
        LambdaQueryWrapper<AiChatSession> q = new LambdaQueryWrapper<>();
        q.eq(AiChatSession::getId, sessionId)
                .eq(AiChatSession::getTenantId, tenantId == null ? 1L : tenantId)
                .eq(AiChatSession::getUserId, userId)
                .eq(AiChatSession::getDeleted, 0);
        AiChatSession s = sessionMapper.selectOne(q);
        if (s == null) {
            throw new BizException(10404, "会话不存在或无权访问");
        }
        return s;
    }

    public AiChatSession rename(Long tenantId, Long userId, Long sessionId, String title) {
        if (!StringUtils.hasText(title)) {
            throw new BizException(10400, "标题不能为空");
        }
        AiChatSession s = require(tenantId, userId, sessionId);
        s.setTitle(trimTitle(title));
        s.setUpdateTime(LocalDateTime.now());
        sessionMapper.updateById(s);
        return s;
    }

    public void delete(Long tenantId, Long userId, Long sessionId) {
        AiChatSession s = require(tenantId, userId, sessionId);
        s.setDeleted(1);
        s.setUpdateTime(LocalDateTime.now());
        sessionMapper.updateById(s);
    }

    public List<AiChatMessage> messages(Long tenantId, Long userId, Long sessionId) {
        require(tenantId, userId, sessionId);
        LambdaQueryWrapper<AiChatMessage> q = new LambdaQueryWrapper<>();
        q.eq(AiChatMessage::getSessionId, sessionId)
                .eq(AiChatMessage::getTenantId, tenantId == null ? 1L : tenantId)
                .eq(AiChatMessage::getUserId, userId)
                .orderByAsc(AiChatMessage::getId);
        return messageMapper.selectList(q);
    }

    /**
     * 撤回前置信息：这一轮删什么、有哪些工具调用、是否含写操作。
     * 副作用判定只看已落库的 tool_calls，不做关键词猜测。
     */
    public Map<String, Object> recallInfo(Long tenantId, Long userId, Long sessionId, Long messageId) {
        AiChatMessage user = requireUserMessage(tenantId, userId, sessionId, messageId);
        AiChatMessage reply = findReply(tenantId, userId, sessionId, user.getId());
        List<String> tools = toolNames(reply);
        boolean sideEffects = tools.stream().anyMatch(n -> !READ_ONLY_TOOLS.contains(n));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("userMessageId", String.valueOf(user.getId()));
        out.put("assistantMessageId", reply == null ? null : String.valueOf(reply.getId()));
        out.put("tools", tools);
        out.put("sideEffects", sideEffects);
        return out;
    }

    /**
     * 撤回 = 物理删除：删掉该条用户消息 + 由它触发的那条 AI 回复，并清掉其他消息对这两条的引用。
     * 有写操作时必须 force=true（前端先弹确认）。
     * 删除顺序：先清掉其他消息对这两条的引用 → 再删两条消息 → 最后按需重算会话标题，全部在同一事务内。
     */
    @Transactional
    public Map<String, Object> deleteRound(Long tenantId, Long userId, Long sessionId, Long messageId,
                                           boolean force) {
        AiChatMessage user = requireUserMessage(tenantId, userId, sessionId, messageId);
        require(tenantId, userId, sessionId);
        AiChatMessage reply = findReply(tenantId, userId, sessionId, user.getId());

        List<String> tools = toolNames(reply);
        boolean sideEffects = tools.stream().anyMatch(n -> !READ_ONLY_TOOLS.contains(n));
        if (sideEffects && !force) {
            throw new BizException(10409, "该轮包含写操作，请确认后再撤回");
        }

        List<Long> ids = new ArrayList<>();
        ids.add(user.getId());
        if (reply != null) {
            ids.add(reply.getId());
        }
        LambdaUpdateWrapper<AiChatMessage> clearQuote = new LambdaUpdateWrapper<>();
        clearQuote.eq(AiChatMessage::getSessionId, sessionId)
                .in(AiChatMessage::getQuotedMessageId, ids)
                .set(AiChatMessage::getQuotedMessageId, null)
                .set(AiChatMessage::getQuotedRole, null)
                .set(AiChatMessage::getQuotedContent, "引用的消息已删除");
        messageMapper.update(null, clearQuote);

        for (Long id : ids) {
            messageMapper.deleteById(id);
        }

        // 标题若来自被删的这条消息，则用剩余最早的一条用户消息重算；否则保留（尊重手动改名）
        AiChatSession session = sessionMapper.selectById(sessionId);
        String autoTitle = trimTitle(user.getContent());
        if (session != null && autoTitle.equals(session.getTitle())) {
            AiChatMessage firstUser = firstUserMessage(sessionId);
            session.setTitle(firstUser == null ? DEFAULT_TITLE : trimTitle(firstUser.getContent()));
            session.setUpdateTime(LocalDateTime.now());
            sessionMapper.updateById(session);
        }

        Map<String, Object> out = new LinkedHashMap<>();
        out.put("deletedMessageIds", ids.stream().map(String::valueOf).toList());
        out.put("sideEffects", sideEffects);
        out.put("sessionTitle", session == null ? null : session.getTitle());
        return out;
    }

    private AiChatMessage requireUserMessage(Long tenantId, Long userId, Long sessionId, Long messageId) {
        AiChatMessage m = requireMessage(tenantId, userId, sessionId, messageId);
        if (!"user".equals(m.getRole())) {
            throw new BizException(10403, "只能撤回自己发送的消息");
        }
        return m;
    }

    /** 该用户消息之后的第一条 assistant 消息，即这一轮的回复 */
    private AiChatMessage findReply(Long tenantId, Long userId, Long sessionId, Long userMessageId) {
        LambdaQueryWrapper<AiChatMessage> q = new LambdaQueryWrapper<>();
        q.eq(AiChatMessage::getSessionId, sessionId)
                .eq(AiChatMessage::getTenantId, tenantId == null ? 1L : tenantId)
                .eq(AiChatMessage::getUserId, userId)
                .eq(AiChatMessage::getRole, "assistant")
                .gt(AiChatMessage::getId, userMessageId)
                .orderByAsc(AiChatMessage::getId)
                .last("LIMIT 1");
        return messageMapper.selectOne(q);
    }

    private AiChatMessage firstUserMessage(Long sessionId) {
        LambdaQueryWrapper<AiChatMessage> q = new LambdaQueryWrapper<>();
        q.eq(AiChatMessage::getSessionId, sessionId)
                .eq(AiChatMessage::getRole, "user")
                .orderByAsc(AiChatMessage::getId)
                .last("LIMIT 1");
        return messageMapper.selectOne(q);
    }

    private List<String> toolNames(AiChatMessage reply) {
        List<String> names = new ArrayList<>();
        if (reply == null || !StringUtils.hasText(reply.getToolCalls())) {
            return names;
        }
        try {
            JsonNode arr = objectMapper.readTree(reply.getToolCalls());
            for (JsonNode n : arr) {
                String name = n.path("name").asText("");
                if (StringUtils.hasText(name)) {
                    names.add(name);
                }
            }
        } catch (Exception ignored) {
            // 历史脏数据解析失败时按“无工具调用”处理
        }
        return names;
    }

    /** 校验并取出一条属于该会话的消息（引用回复用）；越权/不存在抛 10404 */
    public AiChatMessage requireMessage(Long tenantId, Long userId, Long sessionId, Long messageId) {
        AiChatMessage m = messageId == null ? null : messageMapper.selectById(messageId);
        if (m == null || !Objects.equals(m.getTenantId(), tenantId == null ? 1L : tenantId)
                || !Objects.equals(m.getUserId(), userId)
                || !Objects.equals(m.getSessionId(), sessionId)) {
            throw new BizException(10404, "引用的消息不存在或无权访问");
        }
        return m;
    }

    /** 多轮窗口：最近 N 条，按时间正序返回（用于拼进 LLM messages） */
    public List<AiChatMessage> recentWindow(Long tenantId, Long userId, Long sessionId) {
        LambdaQueryWrapper<AiChatMessage> q = new LambdaQueryWrapper<>();
        q.eq(AiChatMessage::getSessionId, sessionId)
                .eq(AiChatMessage::getTenantId, tenantId == null ? 1L : tenantId)
                .eq(AiChatMessage::getUserId, userId)
                .orderByDesc(AiChatMessage::getId)
                .last("LIMIT " + HISTORY_WINDOW);
        List<AiChatMessage> list = new ArrayList<>(messageMapper.selectList(q));
        Collections.reverse(list);
        return list;
    }

    public AiChatMessage addMessage(Long tenantId, Long userId, Long sessionId, String role, String content,
                                    String model, String toolCallsJson, String usageJson) {
        return addMessage(tenantId, userId, sessionId, role, content, model, toolCallsJson, usageJson, null, null, null);
    }

    /** 带引用信息的落库：quoted 三个参数为 null 时与旧行为一致 */
    public AiChatMessage addMessage(Long tenantId, Long userId, Long sessionId, String role, String content,
                                    String model, String toolCallsJson, String usageJson,
                                    Long quotedMessageId, String quotedRole, String quotedContent) {
        AiChatMessage m = new AiChatMessage();
        m.setSessionId(sessionId);
        m.setTenantId(tenantId == null ? 1L : tenantId);
        m.setUserId(userId);
        m.setRole(role);
        m.setContent(content == null ? "" : content);
        m.setQuotedMessageId(quotedMessageId);
        m.setQuotedRole(quotedRole);
        m.setQuotedContent(quotedContent);
        m.setModel(model);
        m.setToolCalls(toolCallsJson);
        m.setUsageJson(usageJson);
        m.setCreateTime(LocalDateTime.now());
        messageMapper.insert(m);
        return m;
    }

    /** 首轮用户消息自动命名，并刷新会话时间（会话列表按活跃度排序） */
    public AiChatSession touch(AiChatSession session, String userText) {
        session.setUpdateTime(LocalDateTime.now());
        if (DEFAULT_TITLE.equals(session.getTitle()) && StringUtils.hasText(userText)) {
            session.setTitle(trimTitle(userText));
        }
        sessionMapper.updateById(session);
        return session;
    }

    /** 仅刷新时间（重命名/继续对话时用） */
    public void touchOnly(Long sessionId) {
        LambdaUpdateWrapper<AiChatSession> u = new LambdaUpdateWrapper<>();
        u.eq(AiChatSession::getId, sessionId).set(AiChatSession::getUpdateTime, LocalDateTime.now());
        sessionMapper.update(null, u);
    }

    private String trimTitle(String title) {
        String t = title.replaceAll("\\s+", " ").trim();
        return t.length() > 24 ? t.substring(0, 24) + "…" : t;
    }

    private void requireUser(Long userId) {
        if (userId == null) {
            throw new BizException(10400, "userId 必填");
        }
    }
}
