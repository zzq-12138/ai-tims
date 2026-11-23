-- ============================================================
-- M6+ 五元组对齐 + 条件化知识表示（P0/P2）
-- 目的：让现网抽取/审核/入库字段与离线五元组实验口径一致，
--       并把「适用条件」从正文文本提升为可查询、可过滤的结构化字段。
-- 应用：mysql -udev -p -D aitims < 20261107_m6_pentad_condition.sql
-- 兼容：只新增列，不改既有列；旧行新列为 NULL，读取侧按空值降级，
--       默认单轮抽取链路行为不变（新增能力由配置开关控制）。
-- 幂等：MySQL 8.0 不支持 ADD COLUMN IF NOT EXISTS，本脚本只执行一次；
--       重复执行会报 Duplicate column name，属预期。
-- ============================================================

-- ------------------------------------------------------------
-- 1. ai_extracted：抽取中间表补齐五元组槽位
--    链式抽取（P0）每一步的中间结果写 chain_trace，便于逐步骤校验与人工复核。
-- ------------------------------------------------------------
ALTER TABLE `ai_extracted`
  ADD COLUMN `root_cause`              TEXT         COMMENT '根因结论句（无最终根因时 NULL）' AFTER `fault_phenomenon`,
  ADD COLUMN `root_cause_evidence`     TEXT         COMMENT '根因原文依据（不得改写原文）' AFTER `root_cause`,
  ADD COLUMN `verification`            TEXT         COMMENT '验证方式/结果（如复测温度稳定 85±2℃）' AFTER `root_cause_evidence`,
  ADD COLUMN `verification_evidence`   TEXT         COMMENT '验证依据原文' AFTER `verification`,
  ADD COLUMN `apply_conditions`        JSON         COMMENT '适用条件数组 [{type,value}]，type 五类' AFTER `verification_evidence`,
  ADD COLUMN `condition_keys`          VARCHAR(512) DEFAULT NULL COMMENT '条件扁平键，检索/过滤用，如 device_model=LAM-600|process_stage=贴合' AFTER `apply_conditions`,
  ADD COLUMN `excluded_hypotheses`     JSON         COMMENT '被排除假设 [{hypothesis,evidence}]' AFTER `condition_keys`,
  ADD COLUMN `has_final_root_cause`    TINYINT      NOT NULL DEFAULT 0 COMMENT '是否有最终根因 0/1' AFTER `excluded_hypotheses`,
  ADD COLUMN `relation_type`           VARCHAR(16)  DEFAULT NULL COMMENT '与最相似条目的关系 duplicate/variant/conflict/unrelated（P1 判别结果）' AFTER `dedup_note`,
  ADD COLUMN `relation_confidence`     DECIMAL(4,3) DEFAULT NULL COMMENT '关系判别置信度 0.000-1.000' AFTER `relation_type`,
  ADD COLUMN `chain_trace`             JSON         COMMENT '链式抽取三步原始/校验结果（单轮模式为 NULL）' AFTER `relation_confidence`;

ALTER TABLE `ai_extracted`
  ADD KEY `idx_tenant_relation` (`tenant_id`, `relation_type`);

-- ------------------------------------------------------------
-- 2. kb_knowledge：知识主表同步五元组字段
--    content 仍为向量化主文本；新增字段用于审核展示、条件过滤与解释。
-- ------------------------------------------------------------
ALTER TABLE `kb_knowledge`
  ADD COLUMN `root_cause`        TEXT         COMMENT '根因结论句' AFTER `content`,
  ADD COLUMN `verification`      TEXT         COMMENT '验证方式/结果' AFTER `root_cause`,
  ADD COLUMN `apply_conditions`  JSON         COMMENT '适用条件数组 [{type,value}]' AFTER `verification`,
  ADD COLUMN `condition_keys`    VARCHAR(512) DEFAULT NULL COMMENT '条件扁平键，检索过滤用' AFTER `apply_conditions`;

ALTER TABLE `kb_knowledge`
  ADD KEY `idx_tenant_condition` (`tenant_id`, `condition_keys`(191));

-- ------------------------------------------------------------
-- 3. 回滚（按需执行；会丢失新增字段数据）
-- ------------------------------------------------------------
-- ALTER TABLE `ai_extracted`
--   DROP KEY `idx_tenant_relation`,
--   DROP COLUMN `root_cause`, DROP COLUMN `root_cause_evidence`,
--   DROP COLUMN `verification`, DROP COLUMN `verification_evidence`,
--   DROP COLUMN `apply_conditions`, DROP COLUMN `condition_keys`,
--   DROP COLUMN `excluded_hypotheses`, DROP COLUMN `has_final_root_cause`,
--   DROP COLUMN `relation_type`, DROP COLUMN `relation_confidence`,
--   DROP COLUMN `chain_trace`;
-- ALTER TABLE `kb_knowledge`
--   DROP KEY `idx_tenant_condition`,
--   DROP COLUMN `root_cause`, DROP COLUMN `verification`,
--   DROP COLUMN `apply_conditions`, DROP COLUMN `condition_keys`;
