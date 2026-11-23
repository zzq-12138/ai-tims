-- C 档兜底建议 × 实际处置 配对记录（M6 增量，仅记录，不自动吸纳）
-- 执行方式：确认目标库后手动执行；本文档只提供 DDL，不随服务启动自动建表。
-- 说明：C 档（知识库门控判定无可推送条目）时由大模型生成自由建议，标记 no_kb_basis=1；
--       工单关闭后通过接口回填实际处置，并与建议做字符二元组 Dice 比对，结果写入 consistent/consistency_score。
CREATE TABLE IF NOT EXISTS `ai_fallback_pair` (
  `id`                 BIGINT       NOT NULL COMMENT '主键（雪花）',
  `tenant_id`          BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID',
  `ticket_id`          BIGINT       DEFAULT NULL COMMENT '工单ID（问答时未带工单则为空）',
  `ticket_no`          VARCHAR(64)  DEFAULT NULL COMMENT '工单号',
  `tier`               VARCHAR(4)   NOT NULL DEFAULT 'C' COMMENT '触发档位，固定 C',
  `suggestion_text`    MEDIUMTEXT   NOT NULL COMMENT '模型自由建议原文（不含“仅供参考”前缀）',
  `model`              VARCHAR(64)  DEFAULT NULL COMMENT '生成建议所用模型',
  `prompt_version`     VARCHAR(64)  DEFAULT NULL COMMENT 'prompt 版本（CHAT 版本+fallback-v1）',
  `no_kb_basis`        TINYINT      NOT NULL DEFAULT 1 COMMENT '是否无知识库依据：1是 0否',
  `suggest_time`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '建议生成时间',
  `actual_disposition` TEXT         DEFAULT NULL COMMENT '工单关闭时回填的实际处置',
  `disposition_by`     BIGINT       DEFAULT NULL COMMENT '回填人（登录用户ID）',
  `disposition_time`   DATETIME     DEFAULT NULL COMMENT '回填时间',
  `consistent`         TINYINT      DEFAULT NULL COMMENT '是否一致：1一致 0不一致 NULL未回填/无法判定',
  `consistency_score`  DECIMAL(5,4) DEFAULT NULL COMMENT '字符二元组 Dice 相似度（0-1）',
  PRIMARY KEY (`id`),
  KEY `idx_fallback_ticket` (`tenant_id`, `ticket_id`),
  KEY `idx_fallback_time` (`tenant_id`, `suggest_time`),
  KEY `idx_fallback_pending` (`tenant_id`, `consistent`, `suggest_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='C档兜底建议与实际处置配对记录';
