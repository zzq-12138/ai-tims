-- 建议→回填：配对记录增加工单标题快照（2026-11-25）
-- 适用：MySQL 8.0；执行一次即可，不需要重跑 20261118_schema_full.sql（新库按顺序执行历史增量脚本与本文件）。
-- 背景：ai_extracted.title 在 FALLBACK 分支原先取“实际处置首行”，会把 AI 回答开头（如「知识库暂无相关记录。」）
--       当成标题。改为回填投递时带上工单标题，待审标题优先用它生成；旧行该列为 NULL，仍按处置首行降级。

ALTER TABLE ai_fallback_pair
    ADD COLUMN ticket_title VARCHAR(128) NULL COMMENT '工单标题快照（可空，回填入库时用于生成待审标题）' AFTER ticket_no;

-- 回滚（按需执行）：
-- ALTER TABLE ai_fallback_pair DROP COLUMN ticket_title;
