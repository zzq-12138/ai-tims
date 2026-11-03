package com.tims.push.service;

import com.baomidou.mybatisplus.core.conditions.query.LambdaQueryWrapper;
import com.tims.push.config.PushTenantContext;
import com.tims.push.entity.PsPushLatency;
import com.tims.push.mapper.PsPushLatencyMapper;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.DoubleSummaryStatistics;
import java.util.List;
import java.util.Map;

/**
 * 四时间戳埋点服务（M4）：
 * t_created 建单落库（事件体携带）→ t_event_sent MQ 发出（事件体携带）
 * → t_retrieve_done 检索返回（管线写入）→ t_push_sent WS 发出（管线写入）。
 * 一条工单一行（uk_ticket 幂等，事件重投不重复建行）；degraded 位标记见 init.sql 注释。
 */
@Service
public class LatencyService {

    private final PsPushLatencyMapper mapper;

    public LatencyService(PsPushLatencyMapper mapper) {
        this.mapper = mapper;
    }

    /** ticket.created 到达：初始化埋点行（幂等） */
    public void initRow(Long ticketId, String ticketNo, String deviceType,
                        LocalDateTime tCreated, LocalDateTime tEventSent, int degraded) {
        PsPushLatency exist = mapper.selectOne(new LambdaQueryWrapper<PsPushLatency>()
                .eq(PsPushLatency::getTicketId, ticketId));
        if (exist != null) {
            PsPushLatency patch = new PsPushLatency();
            patch.setId(exist.getId());
            patch.settCreated(tCreated);
            patch.settEventSent(tEventSent);
            patch.setDegraded(degraded);
            mapper.updateById(patch);
            return;
        }
        PsPushLatency row = new PsPushLatency();
        row.setTenantId(PushTenantContext.resolve());
        row.setTicketId(ticketId);
        row.setTicketNo(ticketNo);
        row.setDeviceType(deviceType);
        row.settCreated(tCreated);
        row.settEventSent(tEventSent);
        row.setDegraded(degraded);
        mapper.insert(row);
    }

    /** 管线完成：写 t_retrieve_done / t_push_sent / 最终 degraded / e2e_ms */
    public void completeRow(Long ticketId, LocalDateTime tRetrieveDone,
                            LocalDateTime tPushSent, int degraded) {
        PsPushLatency exist = mapper.selectOne(new LambdaQueryWrapper<PsPushLatency>()
                .eq(PsPushLatency::getTicketId, ticketId));
        if (exist == null) {
            initRow(ticketId, null, null, tRetrieveDone, tRetrieveDone, degraded);
            exist = mapper.selectOne(new LambdaQueryWrapper<PsPushLatency>()
                    .eq(PsPushLatency::getTicketId, ticketId));
        }
        PsPushLatency patch = new PsPushLatency();
        patch.setId(exist.getId());
        patch.settRetrieveDone(tRetrieveDone);
        patch.settPushSent(tPushSent);
        patch.setDegraded(exist.getDegraded() == null ? degraded : (exist.getDegraded() | degraded));
        if (exist.gettCreated() != null) {
            patch.setE2eMs(Duration.between(exist.gettCreated(), tPushSent).toMillis());
        }
        mapper.updateById(patch);
    }

    /** 统计：最近 limit 条已完成推送的埋点 → P50/P95/P99 + 分段均值 */
    public Map<String, Object> stats(int limit) {
        List<PsPushLatency> rows = mapper.selectList(new LambdaQueryWrapper<PsPushLatency>()
                .isNotNull(PsPushLatency::gettPushSent)
                .orderByDesc(PsPushLatency::getId)
                .last("LIMIT " + Math.max(1, Math.min(limit, 2000))));
        List<Double> e2e = new ArrayList<>();
        List<Double> segEvent = new ArrayList<>();
        List<Double> segRetrieve = new ArrayList<>();
        List<Double> segPush = new ArrayList<>();
        int degradedCount = 0;
        for (PsPushLatency r : rows) {
            if (r.gettCreated() != null) {
                e2e.add(Duration.between(r.gettCreated(), r.gettPushSent()).toNanos() / 1e6);
            }
            if (r.gettCreated() != null && r.gettEventSent() != null) {
                segEvent.add(Duration.between(r.gettCreated(), r.gettEventSent()).toNanos() / 1e6);
            }
            if (r.gettEventSent() != null && r.gettRetrieveDone() != null) {
                segRetrieve.add(Duration.between(r.gettEventSent(), r.gettRetrieveDone()).toNanos() / 1e6);
            }
            if (r.gettRetrieveDone() != null) {
                segPush.add(Duration.between(r.gettRetrieveDone(), r.gettPushSent()).toNanos() / 1e6);
            }
            if (r.getDegraded() != null && r.getDegraded() != 0) degradedCount++;
        }
        Map<String, Object> out = new java.util.LinkedHashMap<>();
        out.put("count", rows.size());
        out.put("degradedCount", degradedCount);
        out.put("e2eMs", dist(e2e));
        out.put("segCreateToEventMs", dist(segEvent));
        out.put("segEventToRetrieveMs", dist(segRetrieve));
        out.put("segRetrieveToPushMs", dist(segPush));
        return out;
    }

    private Map<String, Object> dist(List<Double> v) {
        Map<String, Object> m = new java.util.LinkedHashMap<>();
        if (v.isEmpty()) {
            m.put("p50", null); m.put("p95", null); m.put("p99", null); m.put("avg", null);
            return m;
        }
        List<Double> sorted = new ArrayList<>(v.stream().sorted().toList());
        DoubleSummaryStatistics st = sorted.stream().mapToDouble(Double::doubleValue).summaryStatistics();
        m.put("p50", Math.round(percentile(sorted, 0.50)));
        m.put("p95", Math.round(percentile(sorted, 0.95)));
        m.put("p99", Math.round(percentile(sorted, 0.99)));
        m.put("avg", Math.round(st.getAverage()));
        return m;
    }

    private double percentile(List<Double> sorted, double p) {
        int n = sorted.size();
        double idx = p * (n - 1);
        int lo = (int) Math.floor(idx);
        int hi = (int) Math.ceil(idx);
        if (lo == hi) return sorted.get(lo);
        return sorted.get(lo) + (sorted.get(hi) - sorted.get(lo)) * (idx - lo);
    }
}
