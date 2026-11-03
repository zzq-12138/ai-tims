package com.tims.push.entity;

import com.baomidou.mybatisplus.annotation.IdType;
import com.baomidou.mybatisplus.annotation.TableId;
import com.baomidou.mybatisplus.annotation.TableName;

import java.time.LocalDateTime;

/** 推送端到端时延埋点（ps_push_latency，M4 四时间戳，一条工单一行） */
@TableName("ps_push_latency")
public class PsPushLatency {

    @TableId(type = IdType.ASSIGN_ID)
    private Long id;

    private Long tenantId;

    private Long ticketId;

    private String ticketNo;

    private String deviceType;

    /** 建单落库 */
    private LocalDateTime tCreated;

    /** MQ 事件发出 */
    private LocalDateTime tEventSent;

    /** 检索返回 */
    private LocalDateTime tRetrieveDone;

    /** WS 推送发出 */
    private LocalDateTime tPushSent;

    /** 降级位：1=kb关键词降级 2=MQ降级 4=kb全不可用 */
    private Integer degraded;

    /** 端到端耗时 ms */
    private Long e2eMs;

    private LocalDateTime createTime;

    private LocalDateTime updateTime;

    public Long getId() { return id; }
    public void setId(Long id) { this.id = id; }
    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public Long getTicketId() { return ticketId; }
    public void setTicketId(Long ticketId) { this.ticketId = ticketId; }
    public String getTicketNo() { return ticketNo; }
    public void setTicketNo(String ticketNo) { this.ticketNo = ticketNo; }
    public String getDeviceType() { return deviceType; }
    public void setDeviceType(String deviceType) { this.deviceType = deviceType; }
    public LocalDateTime gettCreated() { return tCreated; }
    public void settCreated(LocalDateTime tCreated) { this.tCreated = tCreated; }
    public LocalDateTime gettEventSent() { return tEventSent; }
    public void settEventSent(LocalDateTime tEventSent) { this.tEventSent = tEventSent; }
    public LocalDateTime gettRetrieveDone() { return tRetrieveDone; }
    public void settRetrieveDone(LocalDateTime tRetrieveDone) { this.tRetrieveDone = tRetrieveDone; }
    public LocalDateTime gettPushSent() { return tPushSent; }
    public void settPushSent(LocalDateTime tPushSent) { this.tPushSent = tPushSent; }
    public Integer getDegraded() { return degraded; }
    public void setDegraded(Integer degraded) { this.degraded = degraded; }
    public Long getE2eMs() { return e2eMs; }
    public void setE2eMs(Long e2eMs) { this.e2eMs = e2eMs; }
    public LocalDateTime getCreateTime() { return createTime; }
    public void setCreateTime(LocalDateTime createTime) { this.createTime = createTime; }
    public LocalDateTime getUpdateTime() { return updateTime; }
    public void setUpdateTime(LocalDateTime updateTime) { this.updateTime = updateTime; }
}
