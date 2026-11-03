package com.tims.order.dto;

/** 工单列表查询（§6.3 #2）：tab(TODO/DONE/MINE/CC/ALL) + 过滤条件 + 分页 */
public class TicketPageQuery {

    /** TODO=待我处理 DONE=我处理的 MINE=我发起的 CC=抄送我的(暂同 MINE，M4 接入抄送) ALL=全部 */
    private String tab = "ALL";

    private String status;
    private String ticketType;
    private String triggerType;
    private String factory;

    /** 关键词：编号/标题/描述模糊 */
    private String keyword;

    private long page = 1;
    private long size = 10;

    public String getTab() { return tab; }
    public void setTab(String tab) { this.tab = tab; }
    public String getStatus() { return status; }
    public void setStatus(String status) { this.status = status; }
    public String getTicketType() { return ticketType; }
    public void setTicketType(String ticketType) { this.ticketType = ticketType; }
    public String getTriggerType() { return triggerType; }
    public void setTriggerType(String triggerType) { this.triggerType = triggerType; }
    public String getFactory() { return factory; }
    public void setFactory(String factory) { this.factory = factory; }
    public String getKeyword() { return keyword; }
    public void setKeyword(String keyword) { this.keyword = keyword; }
    public long getPage() { return page; }
    public void setPage(long page) { this.page = page; }
    public long getSize() { return size; }
    public void setSize(long size) { this.size = size; }
}
