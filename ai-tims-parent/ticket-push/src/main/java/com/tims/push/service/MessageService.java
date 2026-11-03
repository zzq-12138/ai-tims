package com.tims.push.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.push.entity.PsPushMessage;
import com.tims.push.mapper.PsPushMessageMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.LocalDateTime;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 站内消息服务（M4）：离线坐席落库、上线/接入时补推。
 * takeUnreadForPush 返回卡片数据并标记 pushed_flag=1（防重复补推）。
 */
@Service
public class MessageService {

    private static final Logger log = LoggerFactory.getLogger(MessageService.class);

    private final PsPushMessageMapper messageMapper;

    public MessageService(PsPushMessageMapper messageMapper) {
        this.messageMapper = messageMapper;
    }

    /** 离线落库（handlerId 等未在线目标） */
    public void saveOffline(Long tenantId, Long ticketId, Long userId, String title, String cardJson) {
        PsPushMessage m = new PsPushMessage();
        m.setTenantId(tenantId);
        m.setTicketId(ticketId);
        m.setUserId(userId);
        m.setMsgType("CARD");
        m.setTitle(title);
        m.setContent(cardJson);
        m.setReadFlag(0);
        m.setPushedFlag(0);
        messageMapper.insert(m);
        log.info("站内消息落库 userId={} ticketId={}", userId, ticketId);
    }

    /** 取未补推消息 → 转卡片数据 → 标记已补推（含 WS 断线重连与 REST 兜底两条路径） */
    public List<Map<String, Object>> takeUnreadForPush(long userId, long tenantId) {
        List<PsPushMessage> list = messageMapper.selectList(new LambdaQueryWrapper<PsPushMessage>()
                .eq(PsPushMessage::getUserId, userId)
                .eq(PsPushMessage::getReadFlag, 0)
                .eq(PsPushMessage::getPushedFlag, 0)
                .orderByAsc(PsPushMessage::getId)
                .last("LIMIT 50"));
        return list.stream().map(m -> {
            Map<String, Object> card = parseCard(m.getContent());
            card.put("messageId", m.getId());
            card.put("offline", true);
            card.put("createTime", String.valueOf(m.getCreateTime()));
            PsPushMessage patch = new PsPushMessage();
            patch.setId(m.getId());
            patch.setPushedFlag(1);
            messageMapper.updateById(patch);
            return card;
        }).toList();
    }

    /** 标记已读（前端点击卡片时调用） */
    public void markRead(Long messageId) {
        PsPushMessage patch = new PsPushMessage();
        patch.setId(messageId);
        patch.setReadFlag(1);
        patch.setReadTime(LocalDateTime.now());
        messageMapper.updateById(patch);
    }

    private Map<String, Object> parseCard(String json) {
        try {
            return new com.fasterxml.jackson.databind.ObjectMapper().readValue(
                    json == null ? "{}" : json, Map.class);
        } catch (Exception e) {
            return new HashMap<>();
        }
    }
}
