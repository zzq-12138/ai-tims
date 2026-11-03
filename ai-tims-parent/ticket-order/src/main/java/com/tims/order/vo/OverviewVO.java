package com.tims.order.vo;

/** 工单统计概览（§6.3 #18）：todoCount/todayCreated/closedRate/adoptionRate */
public class OverviewVO {

    /** 待办数量：SUBMITTED/ACCEPTED/PROCESSING/SUSPENDED */
    private long todoCount;

    /** 今日新建 */
    private long todayCreated;

    /** 关闭率：CLOSED / 非DRAFT总数（0-1） */
    private double closedRate;

    /** AI 采纳率：ai_extracted=1 且 CLOSED / CLOSED（0-1，M2 stub 口径） */
    private double adoptionRate;

    public long getTodoCount() { return todoCount; }
    public void setTodoCount(long todoCount) { this.todoCount = todoCount; }
    public long getTodayCreated() { return todayCreated; }
    public void setTodayCreated(long todayCreated) { this.todayCreated = todayCreated; }
    public double getClosedRate() { return closedRate; }
    public void setClosedRate(double closedRate) { this.closedRate = closedRate; }
    public double getAdoptionRate() { return adoptionRate; }
    public void setAdoptionRate(double adoptionRate) { this.adoptionRate = adoptionRate; }
}
