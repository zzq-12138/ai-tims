package com.tims.ai.dto;

import java.util.List;

/**
 * 知识抽取入参（M6，ticket-knowledge 在 ticket.closed 消费后内部调用）。
 * 字段来自工单详情：标题/描述/设备类型/解决说明/评论。
 */
public class ExtractRequest {

    private Long tenantId;

    private Long ticketId;

    private String ticketNo;

    private String title;

    private String deviceType;

    private String description;

    private String resolveNote;

    private List<String> comments;

    private List<String> flows;

    public Long getTenantId() { return tenantId; }
    public void setTenantId(Long tenantId) { this.tenantId = tenantId; }
    public Long getTicketId() { return ticketId; }
    public void setTicketId(Long ticketId) { this.ticketId = ticketId; }
    public String getTicketNo() { return ticketNo; }
    public void setTicketNo(String ticketNo) { this.ticketNo = ticketNo; }
    public String getTitle() { return title; }
    public void setTitle(String title) { this.title = title; }
    public String getDeviceType() { return deviceType; }
    public void setDeviceType(String deviceType) { this.deviceType = deviceType; }
    public String getDescription() { return description; }
    public void setDescription(String description) { this.description = description; }
    public String getResolveNote() { return resolveNote; }
    public void setResolveNote(String resolveNote) { this.resolveNote = resolveNote; }
    public List<String> getComments() { return comments; }
    public void setComments(List<String> comments) { this.comments = comments; }
    public List<String> getFlows() { return flows; }
    public void setFlows(List<String> flows) { this.flows = flows; }
}
