-- 建议→回填→入库：待审队列来源标记（2026-11-23）
-- 适用：MySQL 8.0；执行一次即可，不需要重跑 20261118_schema_full.sql（新库按顺序执行历史增量脚本与本文件）。
-- 说明：回填条目仍只落 ai_extracted（status=PENDING_REVIEW），人审通过才由既有审核服务写 kb_knowledge。

ALTER TABLE ai_extracted
    ADD COLUMN source_type       VARCHAR(16)  NOT NULL DEFAULT 'EXTRACT' COMMENT '知识来源：EXTRACT 工单抽取 / FALLBACK 建议回填' AFTER source_device_type,
    ADD COLUMN source_ref_id     BIGINT       NULL     COMMENT '来源记录ID：FALLBACK 时为 ai_fallback_pair.id' AFTER source_type,
    ADD COLUMN source_session_id VARCHAR(64)  NULL     COMMENT '来源问答会话ID（可空）' AFTER source_ref_id,
    ADD COLUMN source_confidence DECIMAL(5,4) NULL     COMMENT '来源置信分 0-1（coverage 优先，其次 dice）' AFTER source_session_id,
    ADD INDEX idx_source_type (source_type);

ALTER TABLE ai_fallback_pair
    ADD COLUMN session_id VARCHAR(64) NULL COMMENT '问答会话ID（可空）' AFTER prompt_version;

-- 回滚（按需执行）：
-- ALTER TABLE ai_fallback_pair DROP COLUMN session_id;
-- ALTER TABLE ai_extracted
--     DROP INDEX idx_source_type,
--     DROP COLUMN source_confidence,
--     DROP COLUMN source_session_id,
--     DROP COLUMN source_ref_id,
--     DROP COLUMN source_type;
