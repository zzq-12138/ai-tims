-- ============================================================
-- 增量升级：可观测性 + 租户 API Key 管理（2026-11-07）
-- 适用：已按旧版 init.sql 建过库的环境，执行一次即可
-- 说明：MySQL 8 的 ALTER TABLE 不支持 ADD COLUMN IF NOT EXISTS，
--       若某列已存在会报 1060，忽略该条继续执行后续语句即可。
-- ============================================================

-- 1) ai_call_log 补观测字段
ALTER TABLE `ai_call_log`
  ADD COLUMN `guard_blocked`  TINYINT     NOT NULL DEFAULT 0 COMMENT '是否被安全护栏拦截 0/1' AFTER `degraded`,
  ADD COLUMN `prompt_version` VARCHAR(32) DEFAULT NULL COMMENT 'prompt 版本号，可反查 ai_prompt_version' AFTER `guard_blocked`,
  ADD COLUMN `trace_id`       VARCHAR(48) DEFAULT NULL COMMENT '调用链ID：父调用与工具调用共用' AFTER `prompt_version`,
  ADD KEY `idx_tenant_trace` (`tenant_id`, `trace_id`),
  ADD KEY `idx_tenant_user` (`tenant_id`, `user_id`, `create_time`);

-- 2) prompt 版本存档
CREATE TABLE IF NOT EXISTS `ai_prompt_version` (
  `id`          BIGINT       NOT NULL COMMENT '主键（雪花）',
  `tenant_id`   BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID',
  `scene`       VARCHAR(24)  NOT NULL COMMENT '场景 CHAT/ASSISTANT/AGENT',
  `version`     VARCHAR(32)  NOT NULL COMMENT '版本号，如 chat-v1',
  `content`     MEDIUMTEXT   NOT NULL COMMENT 'prompt 全文存档',
  `active`      TINYINT      NOT NULL DEFAULT 1 COMMENT '是否当前生效 0/1',
  `created_by`  BIGINT       DEFAULT NULL COMMENT '创建人',
  `create_time` DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_tenant_scene_version` (`tenant_id`, `scene`, `version`),
  KEY `idx_tenant_scene_active` (`tenant_id`, `scene`, `active`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='prompt 版本存档';

-- 3) 租户模型 API Key（AES-256-GCM 密文）
CREATE TABLE IF NOT EXISTS `ai_tenant_key` (
  `id`             BIGINT       NOT NULL COMMENT '主键（雪花）',
  `tenant_id`      BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID',
  `provider`       VARCHAR(32)  NOT NULL DEFAULT 'zhipu' COMMENT '模型供应商',
  `model`          VARCHAR(64)  NOT NULL COMMENT '模型名（展示/对账）',
  `api_key_cipher` VARCHAR(512) NOT NULL COMMENT 'AES-256-GCM 密文 v1:iv:data',
  `key_tail`       VARCHAR(8)   DEFAULT NULL COMMENT 'Key 尾号（列表回显）',
  `updated_by`     BIGINT       DEFAULT NULL COMMENT '操作人',
  `update_time`    DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_tenant_provider_model` (`tenant_id`, `provider`, `model`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='租户模型 API Key（密文）';

-- 4) 租户额度（管理员填写，本地估算剩余）
CREATE TABLE IF NOT EXISTS `ai_tenant_quota` (
  `tenant_id`   BIGINT       NOT NULL COMMENT '租户ID（主键）',
  `quota_cny`   DECIMAL(12,4) NOT NULL DEFAULT 0 COMMENT '管理员填写额度（元）',
  `updated_by`  BIGINT       DEFAULT NULL COMMENT '操作人',
  `update_time` DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`tenant_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='租户额度（管理员填写，用于本地估算剩余）';

-- 5) Key 操作审计
CREATE TABLE IF NOT EXISTS `ai_key_audit` (
  `id`          BIGINT       NOT NULL COMMENT '主键（雪花）',
  `tenant_id`   BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID',
  `action`      VARCHAR(16)  NOT NULL COMMENT 'CREATE/UPDATE/DELETE/VIEW/QUOTA',
  `provider`    VARCHAR(32)  DEFAULT NULL COMMENT '模型供应商',
  `model`       VARCHAR(64)  DEFAULT NULL COMMENT '模型名',
  `key_tail`    VARCHAR(8)   DEFAULT NULL COMMENT 'Key 尾号（不记录明文）',
  `operator_id` BIGINT       DEFAULT NULL COMMENT '操作人',
  `detail`      VARCHAR(255) DEFAULT NULL COMMENT '操作说明',
  `create_time` DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '操作时间',
  PRIMARY KEY (`id`),
  KEY `idx_tenant_time` (`tenant_id`, `create_time`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='API Key 操作审计';
