package com.tims.ai.chat;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.baomidou.mybatisplus.core.conditions.update.LambdaUpdateWrapper;
import com.tims.common.exception.BizException;
import org.springframework.stereotype.Service;
import org.springframework.util.StringUtils;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.Collections;
import java.util.List;

/**
 * AI 会话持久化（M6 问题8）。
 * 隔离：所有读写都带 tenant_id + user_id 条件，越权访问按“不存在”处理。
 * 上下文：会话历史从库里取最近 N 条，前端无需回传全部历史（刷新/切会话/换设备一致）。
 */
@Service
public class AiChatSessionService {

    public static final String DEFAULT_TITLE = "新会话";
    private static final int HISTORY_WINDOW = 10;

    private final AiChatSessionMapper sessionMapper;
    private final AiChatMessageMapper messageMapper;

    public AiChatSessionService(AiChatSessionMapper sessionMapper, AiChatMessageMapper messageMapper) {
        this.sessionMapper = sessionMapper;
        this.messageMapper = messageMapper;
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

    public void addMessage(Long tenantId, Long userId, Long sessionId, String role, String content,
                           String model, String toolCallsJson, String usageJson) {
        AiChatMessage m = new AiChatMessage();
        m.setSessionId(sessionId);
        m.setTenantId(tenantId == null ? 1L : tenantId);
        m.setUserId(userId);
        m.setRole(role);
        m.setContent(content == null ? "" : content);
        m.setModel(model);
        m.setToolCalls(toolCallsJson);
        m.setUsageJson(usageJson);
        m.setCreateTime(LocalDateTime.now());
        messageMapper.insert(m);
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
