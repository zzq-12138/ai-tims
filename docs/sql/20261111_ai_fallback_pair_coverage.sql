-- 20261111 兜底配对表：新增“处置侧覆盖率”口径列（与旧 Dice 分数并列保留，不覆盖）
-- 口径：把处置文本切成分句，逐段看“这段能不能在建议原文里找到对应表述”，score = 命中片段数 / 处置片段总数

ALTER TABLE ai_fallback_pair
    ADD COLUMN coverage_score DECIMAL(5,4) NULL COMMENT '处置侧覆盖率 0-1（命中片段数/处置片段总数）' AFTER consistency_score,
    ADD COLUMN coverage_hits INT NULL COMMENT '命中片段数' AFTER coverage_score,
    ADD COLUMN coverage_segments INT NULL COMMENT '处置片段总数' AFTER coverage_hits,
    ADD COLUMN coverage_detail TEXT NULL COMMENT '逐段明细 JSON：片段、是否命中、覆盖度、命中的建议句子' AFTER coverage_segments;
