package com.tims.order.statemachine;

import com.tims.common.exception.BizException;

import java.util.Map;

/**
 * 工单状态机引擎（任务书 §4.1 迁移表 = 唯一事实来源，常量化）。
 * 非法迁移一律抛 BizException(20401)。
 *
 * <pre>
 * create    -                    → SUBMITTED
 * submit    DRAFT                → SUBMITTED
 * accept    SUBMITTED            → ACCEPTED
 * start     ACCEPTED             → PROCESSING
 * suspend   PROCESSING           → SUSPENDED（需 reason）
 * resume    SUSPENDED            → PROCESSING
 * assign    ACCEPTED/PROCESSING/SUSPENDED → 状态不变（转派）
 * resolve   PROCESSING           → RESOLVED（需 resolveNote）
 * confirm   RESOLVED             → CLOSED（发布 ticket.closed）
 * reject    RESOLVED             → PROCESSING（驳回重办）
 * terminate SUBMITTED/ACCEPTED/PROCESSING/SUSPENDED → TERMINATED（ADMIN，需 reason）
 * </pre>
 */
public final class TicketStateMachine {

    /** 非法状态迁移错误码（任务书 2.5：order 段 20401） */
    public static final int ILLEGAL_TRANSITION_CODE = 20401;

    /** 乐观锁并发冲突错误码（M4：状态迁移并发控制） */
    public static final int CONCURRENT_MODIFY_CODE = 20402;

    /** 迁移表：action → (前置状态 → 后置状态)，11 对超 Map.of 上限改用 ofEntries */
    private static final Map<TicketAction, Map<String, String>> TRANSITIONS = Map.ofEntries(
            Map.entry(TicketAction.CREATE, Map.of("*", "SUBMITTED")),
            Map.entry(TicketAction.SUBMIT, Map.of("DRAFT", "SUBMITTED")),
            Map.entry(TicketAction.ACCEPT, Map.of("SUBMITTED", "ACCEPTED")),
            Map.entry(TicketAction.START, Map.of("ACCEPTED", "PROCESSING")),
            Map.entry(TicketAction.SUSPEND, Map.of("PROCESSING", "SUSPENDED")),
            Map.entry(TicketAction.RESUME, Map.of("SUSPENDED", "PROCESSING")),
            // ASSIGN 状态不变，前置校验用
            Map.entry(TicketAction.ASSIGN, Map.of("ACCEPTED", "ACCEPTED",
                    "PROCESSING", "PROCESSING",
                    "SUSPENDED", "SUSPENDED")),
            Map.entry(TicketAction.RESOLVE, Map.of("PROCESSING", "RESOLVED")),
            Map.entry(TicketAction.CONFIRM, Map.of("RESOLVED", "CLOSED")),
            Map.entry(TicketAction.REJECT, Map.of("RESOLVED", "PROCESSING")),
            Map.entry(TicketAction.TERMINATE, Map.of("SUBMITTED", "TERMINATED",
                    "ACCEPTED", "TERMINATED",
                    "PROCESSING", "TERMINATED",
                    "SUSPENDED", "TERMINATED"))
    );

    private TicketStateMachine() {
    }

    /**
     * 校验并返回后置状态；非法迁移抛 20401。
     *
     * @param from   前置状态（CREATE 动作传 null）
     * @param action 动作
     */
    public static String transition(String from, TicketAction action) {
        Map<String, String> table = TRANSITIONS.get(action);
        if (table == null) {
            throw new BizException(ILLEGAL_TRANSITION_CODE, "不支持的动作：" + action);
        }
        String to = table.get(from == null ? "*" : from);
        if (to == null) {
            throw new BizException(ILLEGAL_TRANSITION_CODE,
                    "非法状态迁移：" + (from == null ? "新建" : from) + " --" + action + "-->");
        }
        return to;
    }

    /** 校验但不关心后置状态（ASSIGN 用） */
    public static void check(String from, TicketAction action) {
        transition(from, action);
    }

    /** 终态判断 */
    public static boolean isTerminal(String status) {
        return "CLOSED".equals(status) || "TERMINATED".equals(status);
    }

    /** 节点映射：01 填报 / 02 处理 / 03 确认（§4.2） */
    public static String nodeOf(String status) {
        return switch (status == null ? "" : status) {
            case "DRAFT", "SUBMITTED" -> "01 填报";
            case "ACCEPTED", "PROCESSING", "SUSPENDED" -> "02 处理";
            case "RESOLVED", "CLOSED" -> "03 确认";
            default -> "01 填报";
        };
    }
}
