-- =====================================================================
-- 文件：docs/sql/20261119_m6_flow_backfill_verify.sql
-- 用途：公司库 aitims —— 「真实业务流补跑 AI 抽取」的盘点、试点核对、全量核对语句
-- 执行位置：公司虚拟桌面 Navicat，172.27.19.64:30546，库 aitims，用户 root
-- 说明：本文件全部是 SELECT；回滚不靠 SQL（状态机不可逆），靠第 5 章整表备份恢复。
-- 基线（2026-11-19 实测）：wo_ticket 105 条 = SUBMITTED 103 / PROCESSING 1 / CLOSED 1；
--                          ai_extracted 1 条 MANUAL_REQUIRED；MAX(ai_extracted.id)=2123047102249254913
-- =====================================================================

-- =====================================================================
-- 0. 跑前盘点（备份之前先跑，把结果抄进操作记录）
-- =====================================================================

-- 0.1 工单状态分布：预期 103 / 1 / 1
SELECT status, COUNT(*) AS cnt
FROM wo_ticket
WHERE deleted = 0
GROUP BY status
ORDER BY cnt DESC;

-- 0.2 抽取表现状：预期 1 条
SELECT id, source_ticket_id, source_ticket_no, status, LEFT(error_msg, 80) AS error_msg, create_time
FROM ai_extracted
WHERE tenant_id = 1 AND deleted = 0;

-- 0.3 备份前基线（这三个数要和备份文件、恢复后的结果对得上）
SELECT 'wo_ticket' AS tbl, COUNT(*) AS cnt FROM wo_ticket
UNION ALL SELECT 'wo_ticket_flow', COUNT(*) FROM wo_ticket_flow
UNION ALL SELECT 'ai_extracted', COUNT(*) FROM ai_extracted;

-- 0.4 抽取表当前最大主键（跑完后用它判断"本次新增"）
SELECT MAX(id) AS bak_max_id FROM ai_extracted;

-- =====================================================================
-- 1. 试点 2 条：跑前 / 跑后核对
--    把 <ID1>,<ID2> 换成脚本打印出来的两个工单 id
-- =====================================================================

-- 1.1 跑前：确认这两条是 SUBMITTED，且 resolve_note 为空
SELECT id, ticket_no, status, device_type, ticket_type, ai_extracted,
       (resolve_note IS NULL OR resolve_note = '') AS note_is_empty, title
FROM wo_ticket
WHERE id IN (<ID1>, <ID2>);

-- 1.2 跑后：状态应为 CLOSED，resolve_note 非空
SELECT id, ticket_no, status, current_node, ai_extracted,
       CHAR_LENGTH(resolve_note) AS note_len, LEFT(resolve_note, 80) AS note_head,
       update_time
FROM wo_ticket
WHERE id IN (<ID1>, <ID2>);

-- 1.3 流转记录：SUBMITTED 起步的工单每张应新增 4 条
--     （ACCEPT / START / RESOLVE / CONFIRM），加上原有 1 条 CREATE 共 5 条
SELECT ticket_id, action, from_status, to_status, node_name, operator_name,
       LEFT(comment, 40) AS comment, create_time
FROM wo_ticket_flow
WHERE ticket_id IN (<ID1>, <ID2>)
ORDER BY ticket_id, create_time;

-- 1.4 抽取结果质量（跑后等 20~30 秒再查）
--     判定标准见手册 §6.4：status=PENDING_REVIEW、has_final_root_cause=1、root_cause 非空
SELECT source_ticket_no,
       status,
       title,
       fault_phenomenon,
       root_cause,
       LEFT(root_cause_evidence, 120) AS root_cause_evidence,
       has_final_root_cause,
       solution_steps,
       verification,
       LEFT(error_msg, 80) AS error_msg,
       create_time
FROM ai_extracted
WHERE tenant_id = 1
  AND source_ticket_id IN (<ID1>, <ID2>);

-- =====================================================================
-- 2. 全量跑完后的核对
-- =====================================================================

-- 2.1 状态分布：预期 CLOSED 105（原 1 条 + 本次 104），SUBMITTED/PROCESSING 均为 0
SELECT status, COUNT(*) AS cnt
FROM wo_ticket
WHERE deleted = 0
GROUP BY status
ORDER BY cnt DESC;

-- 2.2 总数：预期 105（原有 1 条 MANUAL_REQUIRED + 本次 104）
SELECT COUNT(*) AS total FROM ai_extracted WHERE tenant_id = 1 AND deleted = 0;

-- 2.3 状态分布：PROCESSING 必须为 0；MANUAL_REQUIRED 逐条能解释
SELECT status, COUNT(*) AS cnt, MIN(create_time) AS first_at, MAX(create_time) AS last_at
FROM ai_extracted
WHERE tenant_id = 1 AND deleted = 0
GROUP BY status
ORDER BY cnt DESC;

-- 2.4 残留 PROCESSING（异步线程没跑完 / Pod 重启丢任务）：预期 0 行
SELECT id, source_ticket_no, status,
       TIMESTAMPDIFF(MINUTE, create_time, NOW()) AS minutes_in_processing
FROM ai_extracted
WHERE tenant_id = 1 AND status = 'PROCESSING'
ORDER BY create_time;

-- 2.5 已关单但没抽取记录（事件丢失 / 消费失败）：预期 0 行
SELECT t.id, t.ticket_no, t.status, t.update_time
FROM wo_ticket t
LEFT JOIN ai_extracted a
       ON a.tenant_id = t.tenant_id
      AND a.source_ticket_id = t.id
      AND a.deleted = 0
WHERE t.deleted = 0
  AND t.status = 'CLOSED'
  AND a.id IS NULL;

-- 2.6 有抽取记录但工单没关（不该出现）：预期 0 行
SELECT a.source_ticket_no, t.status, a.status AS extract_status, a.create_time
FROM ai_extracted a
JOIN wo_ticket t ON t.id = a.source_ticket_id AND t.tenant_id = a.tenant_id
WHERE t.status <> 'CLOSED'
ORDER BY a.create_time;

-- 2.7 本次新增明细：重点看 error_msg 与 has_final_root_cause=0 的条目
--     把 <BAK_MAX_ID> 换成 0.4 查到的值
SELECT source_ticket_no, status, has_final_root_cause,
       LEFT(root_cause, 60) AS root_cause_head,
       LEFT(solution_steps, 60) AS steps_head,
       LEFT(error_msg, 80) AS error_msg, create_time
FROM ai_extracted
WHERE tenant_id = 1 AND id > <BAK_MAX_ID>
ORDER BY id;

-- 2.8 流转日志增量核对：预期 = 103×4 + 1×2 = 414 条
SELECT COUNT(*) AS flows_total FROM wo_ticket_flow;
-- 与 0.3 的备份前数量相减，应等于 414（若有工单被驳回/终止则会不同，按实际解释）

-- =====================================================================
-- 3. 抽样看质量（人工判断用）
-- =====================================================================
SELECT source_ticket_no, title, fault_phenomenon, root_cause, solution_steps
FROM ai_extracted
WHERE tenant_id = 1 AND status = 'PENDING_REVIEW'
ORDER BY create_time DESC
LIMIT 5;

-- =====================================================================
-- 4. 出错时的单条重跑口径（不用于回滚）
--    抽取失败（MANUAL_REQUIRED）可删行后重跑；但工单已经 CLOSED，
--    不能再发 ticket.closed，只能用闭环外的补投方式（本手册不采用）。
--    这里只保留查询，不提供写操作。
-- =====================================================================
SELECT source_ticket_no, status, LEFT(error_msg, 120) AS error_msg, create_time
FROM ai_extracted
WHERE tenant_id = 1 AND status = 'MANUAL_REQUIRED'
ORDER BY create_time;

-- =====================================================================
-- 5. 回滚
--    状态机不可逆：ACCEPT/START/RESOLVE/CONFIRM 是真实业务迁移，
--    wo_ticket_flow 只追加，没有"反向接口"，也没有软删除可退。
--    唯一可靠的回滚 = 用跑前 mysqldump 的三张表整表恢复（见手册 §5.3）。
--    恢复命令在 cmd.exe 执行，不写在本 SQL 文件里，避免误粘贴。
-- =====================================================================
