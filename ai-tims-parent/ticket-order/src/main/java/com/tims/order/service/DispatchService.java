package com.tims.order.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.order.entity.WoDispatchRule;
import com.tims.order.entity.WoTicket;
import com.tims.order.mapper.WoDispatchRuleMapper;
import com.tims.order.mapper.SysAuthMapper;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.stereotype.Service;

import java.util.List;

/**
 * 自动派发（任务书 §4.3）：建单时按 规则表 匹配预填处理人。
 * 匹配维度：ticket_type/device_type/factory（支持 * 通配），
 * 打分：类型命中 4 + 设备命中 2 + 厂区命中 1，同分取规则 priority 高者；
 * 无规则命中 → 兜底配置 tims.order.default-handler。
 */
@Service
public class DispatchService {

    private final WoDispatchRuleMapper ruleMapper;
    private final SysAuthMapper authMapper;

    @Value("${tims.order.default-handler:1}")
    private long defaultHandler;

    public DispatchService(WoDispatchRuleMapper ruleMapper, SysAuthMapper authMapper) {
        this.ruleMapper = ruleMapper;
        this.authMapper = authMapper;
    }

    /** 匹配结果：命中的目标处理人（含兜底），never null */
    public Long matchHandler(Long tenantId, WoTicket ticket) {
        Long hit = matchRule(tenantId, ticket);
        return hit != null ? hit : defaultHandler;
    }

    /** 规则命中目标，未命中返回 null（供区分「规则派发」与「兜底派发」） */
    public Long matchRule(Long tenantId, WoTicket ticket) {
        List<WoDispatchRule> rules = ruleMapper.selectList(new LambdaQueryWrapper<WoDispatchRule>()
                .eq(WoDispatchRule::getEnabled, 1));
        WoDispatchRule best = null;
        int bestScore = -1;
        for (WoDispatchRule r : rules) {
            int score = 0;
            if (!match(r.getTicketType(), ticket.getTicketType())) continue;
            score += 4;
            if (!match(r.getDeviceType(), ticket.getDeviceType())) continue;
            score += 2;
            if (!match(r.getFactory(), ticket.getFactory())) continue;
            score += 1;
            if (score > bestScore || (score == bestScore && best != null
                    && r.getPriority() != null && best.getPriority() != null
                    && r.getPriority() > best.getPriority())) {
                best = r;
                bestScore = score;
            }
        }
        return best != null ? best.getTargetUserId() : null;
    }

    /** 通配匹配：规则值为 * 或与实际值相等 */
    private boolean match(String ruleValue, String actual) {
        if (ruleValue == null || ruleValue.isBlank() || "*".equals(ruleValue)) {
            return true;
        }
        return ruleValue.equals(actual);
    }

    /** 处理人姓名（用于预填 handler_name），查不到返回 null */
    public String userName(Long tenantId, Long userId) {
        var simple = authMapper.selectUserSimple(tenantId, userId);
        return simple == null ? null : (String) simple.get("nickname");
    }
}
