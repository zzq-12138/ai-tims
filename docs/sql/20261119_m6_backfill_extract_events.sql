-- =====================================================================
-- 文件：docs/sql/20261119_m6_backfill_extract_events.sql
-- 用途：公司库 aitims —— 批量补跑 M6 AI 抽取的【只读】盘点与事件 payload 生成，
--       以及跑批后的核对与回滚语句（回滚语句默认注释，确认后再手动放开）。
-- 执行位置：公司虚拟桌面 Navicat 连 172.27.19.64:30546（库 aitims，用户 root），
--           或任何能连到该实例的 mysql 客户端。master1 上没有 mysql 客户端。
-- 表依据：docs/sql/20261118_schema_full.sql
--   wo_ticket    : id / tenant_id / ticket_no / device_type / status / deleted
--   ai_extracted : 唯一键 uk_tenant_ticket(tenant_id, source_ticket_id)，逻辑删 deleted
--
-- 安全边界：本文件 0~1 节全部是 SELECT，不写入任何数据；回滚语句集中在第 2 节，
--           默认被注释，必须人工确认 <BAK_MAX_ID> 后再执行。
-- =====================================================================

-- 生成 payload 时 json 可能较长，放宽 group_concat 上限（本文件实际未用 group_concat，
-- 保留是为了复制粘贴到同一会话里手工聚合时不踩 1024 截断）
SET SESSION group_concat_max_len = 1048576;

-- =====================================================================
-- 0. 盘点（先跑这一段，确认数量和状态分布，不做任何变更）
-- =====================================================================

-- 0.1 有效工单按状态分布：预期合计 105 条，CLOSED 占绝大多数
SELECT t.status, COUNT(*) AS cnt
FROM wo_ticket t
WHERE t.deleted = 0
GROUP BY t.status
ORDER BY cnt DESC;

-- 0.2 现有抽取记录：预期 1 条，status = MANUAL_REQUIRED，工单 WO20261118-0105
SELECT a.id,
       a.source_ticket_id,
       a.source_ticket_no,
       a.status,
       a.error_msg,
       a.create_time
FROM ai_extracted a
WHERE a.tenant_id = 1
  AND a.deleted = 0
ORDER BY a.create_time DESC;

-- 0.3 待补跑数量：预期 104
SELECT COUNT(*) AS pending_cnt
FROM wo_ticket t
LEFT JOIN ai_extracted a
       ON a.tenant_id = t.tenant_id
      AND a.source_ticket_id = t.id
      AND a.deleted = 0
WHERE t.deleted = 0
  AND a.id IS NULL;

-- 0.4 待补跑工单的状态分布：确认这 104 条是不是都在你期望的状态里
--     （抽取不校验状态，若混入 DRAFT/PROCESSING，抽出来的知识质量会差；
--       需要只跑已关闭工单时，用 1.2 里那行被注释掉的 status 过滤）
SELECT t.status, COUNT(*) AS cnt
FROM wo_ticket t
LEFT JOIN ai_extracted a
       ON a.tenant_id = t.tenant_id
      AND a.source_ticket_id = t.id
      AND a.deleted = 0
WHERE t.deleted = 0
  AND a.id IS NULL
GROUP BY t.status
ORDER BY cnt DESC;

-- 0.5 跑批基线：务必记下这个数字（回滚要用），建议连同执行时间一起抄到运维记录里
SELECT MAX(id) AS bak_max_id, NOW() AS baseline_at FROM ai_extracted;

-- =====================================================================
-- 1. 生成事件 payload（一行一条 JSON，只读）
--    字段与 ticket-order 的 EventPublisher 保持一致：
--      eventType / tenantId / ticketId / ticketNo / deviceType
--    消费侧 TicketClosedConsumer 只读 eventType、tenantId、ticketId、ticketNo、deviceType，
--    ticketId 必须是数字，tenantId 必须是数字。
-- =====================================================================

-- 1.1 预览 5 条（先看格式对不对）
SELECT JSON_OBJECT(
         'eventType',  'ticket.closed',
         'tenantId',   t.tenant_id,
         'ticketId',   t.id,
         'ticketNo',   t.ticket_no,
         'deviceType', t.device_type
       ) AS payload
FROM wo_ticket t
LEFT JOIN ai_extracted a
       ON a.tenant_id = t.tenant_id
      AND a.source_ticket_id = t.id
      AND a.deleted = 0
WHERE t.deleted = 0
  AND a.id IS NULL
ORDER BY t.id
LIMIT 5;

-- 1.2 全量 104 条（导出这一列就是 payloads.jsonl）
SELECT JSON_OBJECT(
         'eventType',  'ticket.closed',
         'tenantId',   t.tenant_id,
         'ticketId',   t.id,
         'ticketNo',   t.ticket_no,
         'deviceType', t.device_type
       ) AS payload
FROM wo_ticket t
LEFT JOIN ai_extracted a
       ON a.tenant_id = t.tenant_id
      AND a.source_ticket_id = t.id
      AND a.deleted = 0
WHERE t.deleted = 0
  AND a.id IS NULL
  -- AND t.status = 'CLOSED'   -- 需要只跑已关闭工单时取消本行注释；数量会变，后续 3/101 的分段要同步改
ORDER BY t.id;

-- =====================================================================
-- 2. 跑批后核对
-- =====================================================================

-- 2.1 跑完后按状态汇总：预期 PENDING_REVIEW ≈ 本次成功条数，MANUAL_REQUIRED 为失败条数
SELECT status, COUNT(*) AS cnt, MIN(create_time) AS first_at, MAX(create_time) AS last_at
FROM ai_extracted
WHERE tenant_id = 1
GROUP BY status
ORDER BY cnt DESC;

-- 2.2 本次新增的行（把 <BAK_MAX_ID> 换成 0.5 记下的数字）
-- SELECT id, source_ticket_id, source_ticket_no, status, dedup_action,
--        LEFT(error_msg, 80) AS error_msg, create_time
-- FROM ai_extracted
-- WHERE tenant_id = 1 AND id > <BAK_MAX_ID>
-- ORDER BY id;

-- 2.3 是否还有卡在 PROCESSING（异步任务没跑完 / 服务重启丢失）：
--     预期 0 行；若有，等 5 分钟再看，仍不动就按失败处理（可重跑，见手册 §7.3）
SELECT id, source_ticket_no, status,
       TIMESTAMPDIFF(MINUTE, create_time, NOW()) AS minutes_in_processing
FROM ai_extracted
WHERE tenant_id = 1 AND status = 'PROCESSING'
ORDER BY create_time;

-- 2.4 工单侧被改动的范围：预期只有 ai_extracted 标记从 0 变 1（status 一律不变）
-- SELECT t.id, t.ticket_no, t.status, t.ai_extracted, t.update_time
-- FROM wo_ticket t
-- WHERE t.id IN (SELECT source_ticket_id FROM ai_extracted WHERE tenant_id = 1 AND id > <BAK_MAX_ID>)
-- ORDER BY t.id;

-- =====================================================================
-- 3. 回滚（默认全部注释；只在确认要撤销这次补跑时，逐条人工放开）
--    顺序必须是：3.1 先看 -> 3.2 复位工单标记 -> 3.3 硬删抽取行
--    前提：3.3 之前必须确认 2.3 已经没有 PROCESSING 行，否则删完还会被异步任务回写。
-- =====================================================================

-- 3.1 预览将要删除的行（把 <BAK_MAX_ID> 换成 0.5 记下的数字）
-- SELECT id, source_ticket_id, source_ticket_no, status, create_time
-- FROM ai_extracted
-- WHERE tenant_id = 1 AND id > <BAK_MAX_ID>
-- ORDER BY id;

-- 3.2 复位 wo_ticket.ai_extracted（可选）：把本次抽过的工单标记回 0。
--     不做这一步也不会影响工单状态机，只是"AI 采纳率"统计会把这些算成已提炼。
-- UPDATE wo_ticket t
--   JOIN ai_extracted a
--     ON a.tenant_id = t.tenant_id
--    AND a.source_ticket_id = t.id
-- SET t.ai_extracted = 0
-- WHERE a.tenant_id = 1
--   AND a.id > <BAK_MAX_ID>;

-- 3.3 硬删本次新增的抽取行。
--     不要用软删（deleted=1）：唯一键 uk_tenant_ticket 不看 deleted，
--     软删后重新投事件会撞唯一键，被消费者当成"重复消息"静默跳过。
-- DELETE FROM ai_extracted
-- WHERE tenant_id = 1
--   AND id > <BAK_MAX_ID>;

-- 3.4 删完自查：预期结构是"只剩 1 条 MANUAL_REQUIRED"
-- SELECT status, COUNT(*) FROM ai_extracted WHERE tenant_id = 1 GROUP BY status;
