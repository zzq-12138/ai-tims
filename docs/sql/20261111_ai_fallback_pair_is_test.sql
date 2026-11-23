-- 20261111 兜底配对表：新增测试数据标记列
-- 目的：复测产生的无处置记录保留不删，用 is_test=1 标记；后续统计默认排除（WHERE is_test = 0）
-- 执行顺序：先在本文件执行 ALTER，再执行下方一次性数据订正（幂等）

ALTER TABLE ai_fallback_pair
    ADD COLUMN is_test TINYINT NOT NULL DEFAULT 0 COMMENT '是否测试数据：1 是，0 否；统计默认排除' AFTER consistency_score;

-- 一次性订正（2026-11-11 复测产物）：本次实测截止时间之前、且从未回填处置的记录标记为测试数据。
-- 该语句只在本次清理时执行一次；后续真实业务里的“未回填”记录不应被标记。
UPDATE ai_fallback_pair
SET is_test = 1
WHERE is_test = 0
  AND suggest_time < '2026-11-11 08:20:00'
  AND (actual_disposition IS NULL OR actual_disposition = '');
