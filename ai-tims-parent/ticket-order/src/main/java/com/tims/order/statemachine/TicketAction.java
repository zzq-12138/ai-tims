package com.tims.order.statemachine;

/**
 * 工单动作（任务书 §4.1 迁移表）。
 */
public enum TicketAction {
    CREATE, SUBMIT, ACCEPT, START, SUSPEND, RESUME, ASSIGN, RESOLVE, CONFIRM, REJECT, TERMINATE
}
