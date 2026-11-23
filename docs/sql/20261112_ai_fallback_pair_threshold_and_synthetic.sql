-- 2026-11-12 兜底配对表：阈值判定列 + 合成样本标记列
-- 判定线走配置 tims.ai.fallback.consistent-threshold（默认 0.60）与 min-segments（默认 3）
-- 合成样本用 is_test=2 与 data_source='synthetic' 双重标记，默认统计（is_test=0）不会带出

ALTER TABLE ai_fallback_pair
    ADD COLUMN coverage_verdict VARCHAR(16) NULL COMMENT '新口径判定：CONSISTENT/INCONSISTENT/INSUFFICIENT' AFTER coverage_detail,
    ADD COLUMN data_source VARCHAR(16) NOT NULL DEFAULT 'real' COMMENT '数据来源：real/synthetic' AFTER is_test,
    ADD COLUMN synthetic_class TINYINT NULL COMMENT '合成样本类别：1一致 2部分一致 3同设备另一方案 4答非所问' AFTER data_source,
    ADD COLUMN class_note VARCHAR(255) NULL COMMENT '合成样本归类理由' AFTER synthetic_class;
