package com.tims.order.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.order.config.TenantContext;
import com.tims.order.entity.WoTicket;
import com.tims.order.mapper.WoTicketMapper;
import com.tims.order.vo.OverviewVO;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.stereotype.Service;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeFormatter;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 工单统计（§6.3 #17 #18）。
 * metric/latest（M2 stub）：模拟指标最新值从 Redis tims:mock:metric:{name} 读取，
 * 由 M4 数据模拟引擎持续写入；M2 阶段无写入方时返回空列表。
 */
@Service
public class StatService {

    /** 三类模拟指标（wo_mock_config.metric_name 同名） */
    private static final List<String> METRIC_NAMES =
            List.of("AOI_DEFECT_RATE", "SPC_CPK", "DEVICE_TEMP");
    private static final String METRIC_KEY_PREFIX = "tims:mock:metric:";

    private static final List<String> OPEN_STATUSES =
            List.of("SUBMITTED", "ACCEPTED", "PROCESSING", "SUSPENDED");

    private final WoTicketMapper ticketMapper;
    private final StringRedisTemplate redis;

    public StatService(WoTicketMapper ticketMapper, StringRedisTemplate redis) {
        this.ticketMapper = ticketMapper;
        this.redis = redis;
    }

    public OverviewVO overview() {
        TenantContext.resolve(); // 触发租户上下文（TenantLine 拦截器取同源值）
        OverviewVO vo = new OverviewVO();
        vo.setTodoCount(ticketMapper.selectCount(new LambdaQueryWrapper<WoTicket>()
                .in(WoTicket::getStatus, OPEN_STATUSES)));
        vo.setTodayCreated(ticketMapper.selectCount(new LambdaQueryWrapper<WoTicket>()
                .ge(WoTicket::getCreateTime, LocalDateTime.of(LocalDate.now(), LocalTime.MIN))));
        long total = ticketMapper.selectCount(new LambdaQueryWrapper<WoTicket>()
                .ne(WoTicket::getStatus, "DRAFT"));
        long closed = ticketMapper.selectCount(new LambdaQueryWrapper<WoTicket>()
                .eq(WoTicket::getStatus, "CLOSED"));
        long adopted = ticketMapper.selectCount(new LambdaQueryWrapper<WoTicket>()
                .eq(WoTicket::getStatus, "CLOSED").eq(WoTicket::getAiExtracted, 1));
        vo.setClosedRate(total == 0 ? 0.0 : round4((double) closed / total));
        vo.setAdoptionRate(closed == 0 ? 0.0 : round4((double) adopted / closed));
        return vo;
    }

    /** 模拟指标最新值（stub：Redis 直读，M4 由模拟引擎写入） */
    public List<Map<String, Object>> metricLatest() {
        List<Map<String, Object>> result = new ArrayList<>();
        String now = LocalDateTime.now().format(DateTimeFormatter.ISO_LOCAL_DATE_TIME);
        for (String name : METRIC_NAMES) {
            String v = redis.opsForValue().get(METRIC_KEY_PREFIX + name);
            if (v == null) continue;
            Map<String, Object> m = new LinkedHashMap<>();
            m.put("metricName", name);
            m.put("value", v);
            m.put("time", now);
            result.add(m);
        }
        return result;
    }

    private static double round4(double v) {
        return Math.round(v * 10000) / 10000.0;
    }
}
