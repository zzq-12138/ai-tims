package com.tims.order.vo;

import com.tims.order.entity.WoTicket;
import com.tims.order.entity.WoTicketComment;
import com.tims.order.entity.WoTicketFlow;

import java.util.List;

/** 工单详情（§6.3 #3）：主单 + 流转时间线 + 沟通记录 + 推送记录ID（M2 stub 空数组） */
public class TicketDetailVO {

    private WoTicket ticket;

    private List<WoTicketFlow> flows;

    private List<WoTicketComment> comments;

    /** M3/M4 消息推送回执，M2 预留空数组 */
    private List<Long> pushIds;

    public WoTicket getTicket() { return ticket; }
    public void setTicket(WoTicket ticket) { this.ticket = ticket; }
    public List<WoTicketFlow> getFlows() { return flows; }
    public void setFlows(List<WoTicketFlow> flows) { this.flows = flows; }
    public List<WoTicketComment> getComments() { return comments; }
    public void setComments(List<WoTicketComment> comments) { this.comments = comments; }
    public List<Long> getPushIds() { return pushIds; }
    public void setPushIds(List<Long> pushIds) { this.pushIds = pushIds; }
}
