-- =============================================================================
-- kb_migrate_verify.sql —— 知识库数据迁移到公司库之后的只读校验
--
-- 执行位置：虚拟桌面 Navicat（连公司库），或 kubectl exec 进 mysql 客户端后 source。
-- 全部是 SELECT，不改任何数据；可以在导入后反复执行。
--
-- 预期基线（开发机 320 条 + 公司库原有 1 条测试知识）：
--   总条数              = 321
--   PUBLISHED           = 319
--   PENDING             = 2
--   vector_synced_at 为空 = 318~319（取决于是否把原有测试知识也一起置空）
--
-- 注意：导入后必须先把 vector_synced_at 置空，否则定时任务不会重算向量。
--       置空语句见 kb_migrate_import.md 的「导入后必做三步」。
-- =============================================================================

-- 0) 确认连的是公司库
SELECT DATABASE() AS current_db, VERSION() AS mysql_version;

-- 1) 总条数（同时区分逻辑删除）
SELECT
  COUNT(*)                                   AS total_all,
  SUM(CASE WHEN deleted = 0 THEN 1 ELSE 0 END) AS total_alive
FROM kb_knowledge;

-- 2) 按状态分组
SELECT status, COUNT(*) AS cnt
FROM kb_knowledge
WHERE deleted = 0
GROUP BY status
ORDER BY cnt DESC;

-- 3) 向量同步状态（只统计会被定时任务处理的 PUBLISHED 行）
SELECT
  SUM(CASE WHEN vector_synced_at IS NULL THEN 1 ELSE 0 END)     AS not_synced,
  SUM(CASE WHEN vector_synced_at IS NOT NULL THEN 1 ELSE 0 END) AS synced
FROM kb_knowledge
WHERE status = 'PUBLISHED' AND deleted = 0;

-- 4) 按适用设备类型分组（NULL 是正常情况：很多知识没填设备类型）
SELECT IFNULL(apply_device_type, '(NULL)') AS device_type, COUNT(*) AS cnt
FROM kb_knowledge
WHERE deleted = 0
GROUP BY apply_device_type
ORDER BY cnt DESC;

-- 5) 抽样 3 条，看标题和正文长度是否正常（正文被截断会明显偏短）
SELECT
  id,
  title,
  CHAR_LENGTH(content) AS content_chars,
  CHAR_LENGTH(IFNULL(summary, '')) AS summary_chars,
  status,
  apply_device_type,
  create_by,
  source_ticket_id,
  vector_synced_at
FROM kb_knowledge
WHERE deleted = 0
ORDER BY RAND()
LIMIT 3;

-- 6) 确认公司库原有那条测试知识还在、且没有被覆盖
--    预期：1 行，status=PUBLISHED
SELECT id, title, status, vector_synced_at
FROM kb_knowledge
WHERE id = 2122940268192731138;

-- 7) 创建人分布（开发机侧：257 条 create_by 为 NULL、59 条为 1）
--    是否统一回填为 1 由业务决定，这不影响列表展示
SELECT
  SUM(CASE WHEN create_by IS NULL THEN 1 ELSE 0 END) AS create_by_null,
  SUM(CASE WHEN create_by = 1 THEN 1 ELSE 0 END)     AS create_by_1,
  SUM(CASE WHEN create_by IS NOT NULL AND create_by <> 1 THEN 1 ELSE 0 END) AS create_by_other
FROM kb_knowledge
WHERE deleted = 0;
