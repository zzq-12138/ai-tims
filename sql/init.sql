-- =====================================================================
-- AI-TIMS 数据库初始化脚本（一键重建）
-- 库：aitims（utf8mb4_0900_ai_ci）；多租户口径：共享库共享表 + tenant_id
-- 租户约定：单租户阶段 tenant_id 恒为 1（TenantLineInnerInterceptor M2 启用）
-- 用法：mysql -u dev -p < sql/init.sql
-- 安全：种子管理员密码为 BCrypt（Admin@123），首次登录后必须修改；
--       本脚本不含明文密码，可安全入库
-- =====================================================================

CREATE DATABASE IF NOT EXISTS `aitims`
  DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE `aitims`;

-- ---------------------------------------------------------------------
-- 1. sys_tenant 租户元数据表（多租户方案 2026-11-02 拍板）
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS `sys_tenant`;
CREATE TABLE `sys_tenant` (
  `id`          BIGINT       NOT NULL COMMENT '主键',
  `tenant_code` VARCHAR(32)  NOT NULL COMMENT '租户编码',
  `tenant_name` VARCHAR(64)  NOT NULL COMMENT '租户名称',
  `status`      TINYINT      NOT NULL DEFAULT 1 COMMENT '1启用 0停用',
  `create_time` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted`     TINYINT      NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_tenant_code` (`tenant_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='租户表';

-- ---------------------------------------------------------------------
-- 2. sys_ 系统域四表（任务书 5.1，叠加 tenant_id 与复合索引）
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS `sys_user`;
CREATE TABLE `sys_user` (
  `id`          BIGINT       NOT NULL COMMENT '主键(雪花ID)',
  `tenant_id`   BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID(单租户阶段恒为1)',
  `username`    VARCHAR(32)  NOT NULL COMMENT '登录名',
  `password`    VARCHAR(128) NOT NULL COMMENT '密码(BCrypt)',
  `nickname`    VARCHAR(32)  NOT NULL COMMENT '姓名',
  `dept_id`     BIGINT       DEFAULT NULL COMMENT '部门ID',
  `factory`     VARCHAR(32)  DEFAULT NULL COMMENT '所属厂区',
  `phone`       VARCHAR(16)  NOT NULL COMMENT '手机号(注册必填，格式后端校验)',
  `email`       VARCHAR(64)  NOT NULL COMMENT '邮箱(注册必填，验证码通道)',
  `status`      TINYINT      NOT NULL DEFAULT 1 COMMENT '1启用 0停用',
  `create_time` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted`     TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_tenant_username` (`tenant_id`, `username`),
  UNIQUE KEY `uk_tenant_phone` (`tenant_id`, `phone`),
  UNIQUE KEY `uk_tenant_email` (`tenant_id`, `email`),
  KEY `idx_tenant_dept` (`tenant_id`, `dept_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户表';

DROP TABLE IF EXISTS `sys_role`;
CREATE TABLE `sys_role` (
  `id`          BIGINT      NOT NULL COMMENT '主键',
  `tenant_id`   BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  `role_code`   VARCHAR(32) NOT NULL COMMENT '角色码 ADMIN/DISPATCHER/ENGINEER/USER',
  `role_name`   VARCHAR(32) NOT NULL COMMENT '角色名',
  `remark`      VARCHAR(128) DEFAULT NULL COMMENT '备注',
  `create_time` DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted`     TINYINT     NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_tenant_role_code` (`tenant_id`, `role_code`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='角色表';

DROP TABLE IF EXISTS `sys_user_role`;
CREATE TABLE `sys_user_role` (
  `id`        BIGINT NOT NULL,
  `tenant_id` BIGINT NOT NULL DEFAULT 1 COMMENT '租户ID',
  `user_id`   BIGINT NOT NULL,
  `role_id`   BIGINT NOT NULL,
  PRIMARY KEY (`id`),
  KEY `idx_tenant_user` (`tenant_id`, `user_id`),
  KEY `idx_tenant_role` (`tenant_id`, `role_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='用户角色关联';

DROP TABLE IF EXISTS `sys_dept`;
CREATE TABLE `sys_dept` (
  `id`          BIGINT      NOT NULL,
  `tenant_id`   BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  `parent_id`   BIGINT      NOT NULL DEFAULT 0 COMMENT '父部门 0=根',
  `dept_name`   VARCHAR(64) NOT NULL COMMENT '部门名',
  `factory`     VARCHAR(32) DEFAULT NULL COMMENT '厂区',
  `sort`        INT         NOT NULL DEFAULT 0,
  `create_time` DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time` DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted`     TINYINT     NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_tenant_parent` (`tenant_id`, `parent_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='部门表';

-- ---------------------------------------------------------------------
-- 3. 种子数据（租户 1 = default；admin/Admin@123）
-- ---------------------------------------------------------------------
INSERT INTO `sys_tenant` (`id`, `tenant_code`, `tenant_name`, `status`) VALUES
(1, 'default', '默认租户', 1);

INSERT INTO `sys_role` (`id`, `tenant_id`, `role_code`, `role_name`, `remark`) VALUES
(1, 1, 'ADMIN',      '系统管理员', '全部权限'),
(2, 1, 'DISPATCHER', '调度员',     '工单分派'),
(3, 1, 'ENGINEER',   '工程师',     '工单处理'),
(4, 1, 'USER',       '普通用户',   '工单填报');

INSERT INTO `sys_dept` (`id`, `tenant_id`, `parent_id`, `dept_name`, `factory`, `sort`) VALUES
(1, 1, 0, '集团总部', NULL, 0),
(2, 1, 1, '制造一部', 'F1',  1);

INSERT INTO `sys_user` (`id`, `tenant_id`, `username`, `password`, `nickname`, `dept_id`, `factory`, `phone`, `email`) VALUES
(1, 1, 'admin', '$2a$10$1Qd7ZqwF9yOKPJ1LvvMcW.RiBpbRlnqA4uIAiSsIbXmw5H.jmMuD2', '系统管理员', 1, 'F1', '13800000001', 'admin@aitims.local');

INSERT INTO `sys_user_role` (`id`, `tenant_id`, `user_id`, `role_id`) VALUES
(1, 1, 1, 1);

-- ---------------------------------------------------------------------
-- 4. wo_ 工单域五表（任务书 5.2，统一叠加 tenant_id 与租户前缀复合索引；
--    任务书原 DDL 无 tenant_id，多租户口径 2026-11-02 拍板后统一补齐）
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS `wo_ticket`;
CREATE TABLE `wo_ticket` (
  `id`            BIGINT       NOT NULL COMMENT '主键',
  `tenant_id`     BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID(单租户阶段恒为1)',
  `ticket_no`     VARCHAR(32)  NOT NULL COMMENT '工单编号 WOyyyyMMdd-XXXX',
  `title`         VARCHAR(128) NOT NULL COMMENT '工单名称',
  `ticket_type`   VARCHAR(32)  NOT NULL COMMENT '工单类型 设备异常/品质异常/系统异常/其他',
  `trigger_type`  VARCHAR(16)  NOT NULL DEFAULT 'MANUAL' COMMENT '触发类型 MANUAL/RULE',
  `factory`       VARCHAR(32)  DEFAULT NULL COMMENT '厂区',
  `plant`         VARCHAR(32)  DEFAULT NULL COMMENT '厂别',
  `scene_name`    VARCHAR(64)  DEFAULT NULL COMMENT '场景名称',
  `device_type`   VARCHAR(64)  DEFAULT NULL COMMENT '设备类型',
  `glass_id`      VARCHAR(64)  DEFAULT NULL COMMENT 'Glass ID(可空)',
  `abnormal_time` DATETIME     DEFAULT NULL COMMENT '异常时间',
  `urgency`       TINYINT      NOT NULL DEFAULT 2 COMMENT '紧急程度 1高 2中 3低',
  `description`   TEXT         COMMENT '现象描述',
  `current_node`  VARCHAR(32)  DEFAULT '01 填报' COMMENT '当前节点 01填报/02处理/03确认',
  `status`        VARCHAR(16)  NOT NULL DEFAULT 'SUBMITTED' COMMENT '状态机状态',
  `handler_id`    BIGINT       DEFAULT NULL COMMENT '当前处理人',
  `handler_name`  VARCHAR(32)  DEFAULT NULL COMMENT '处理人姓名',
  `resolve_note`  TEXT         COMMENT '解决说明(知识提炼输入)',
  `ai_extracted`  TINYINT      NOT NULL DEFAULT 0 COMMENT '是否已AI提炼 0/1',
  `create_by`     BIGINT       DEFAULT NULL COMMENT '创建人',
  `create_time`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted`       TINYINT      NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ticket_no` (`ticket_no`),
  KEY `idx_tenant_status_time` (`tenant_id`, `status`, `create_time`),
  KEY `idx_tenant_handler` (`tenant_id`, `handler_id`),
  KEY `idx_tenant_create_by` (`tenant_id`, `create_by`),
  KEY `idx_tenant_type_device` (`tenant_id`, `ticket_type`, `device_type`),
  FULLTEXT KEY `ft_title_desc` (`title`, `description`) WITH PARSER ngram
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工单主表';

DROP TABLE IF EXISTS `wo_ticket_flow`;
CREATE TABLE `wo_ticket_flow` (
  `id`            BIGINT      NOT NULL,
  `tenant_id`     BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  `ticket_id`     BIGINT      NOT NULL COMMENT '工单ID',
  `action`        VARCHAR(32) NOT NULL COMMENT '动作 CREATE/SUBMIT/ACCEPT/START/SUSPEND/RESUME/ASSIGN/RESOLVE/CONFIRM/REJECT/TERMINATE',
  `from_status`   VARCHAR(16) DEFAULT NULL,
  `to_status`     VARCHAR(16) DEFAULT NULL,
  `node_name`     VARCHAR(32) DEFAULT NULL COMMENT '节点 01填报/02处理/03确认',
  `operator_id`   BIGINT      DEFAULT NULL,
  `operator_name` VARCHAR(32) DEFAULT NULL,
  `comment`       VARCHAR(512) DEFAULT NULL COMMENT '处理意见/原因',
  `create_time`   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_tenant_ticket` (`tenant_id`, `ticket_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工单流转记录';

DROP TABLE IF EXISTS `wo_ticket_comment`;
CREATE TABLE `wo_ticket_comment` (
  `id`          BIGINT      NOT NULL,
  `tenant_id`   BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  `ticket_id`   BIGINT      NOT NULL,
  `user_id`     BIGINT      NOT NULL,
  `user_name`   VARCHAR(32) NOT NULL,
  `content`     VARCHAR(1024) NOT NULL COMMENT '内容',
  `source`      VARCHAR(16) NOT NULL DEFAULT 'USER' COMMENT 'USER/AI_ASSISTANT',
  `create_time` DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (`id`),
  KEY `idx_tenant_ticket` (`tenant_id`, `ticket_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工单沟通记录';

DROP TABLE IF EXISTS `wo_dispatch_rule`;
CREATE TABLE `wo_dispatch_rule` (
  `id`             BIGINT      NOT NULL,
  `tenant_id`      BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  `ticket_type`    VARCHAR(32) NOT NULL DEFAULT '*' COMMENT '工单类型(支持*)',
  `device_type`    VARCHAR(64) NOT NULL DEFAULT '*' COMMENT '设备类型(支持*)',
  `factory`        VARCHAR(32) NOT NULL DEFAULT '*' COMMENT '厂区(支持*)',
  `target_user_id` BIGINT      NOT NULL COMMENT '目标处理人',
  `priority`       INT         NOT NULL DEFAULT 0 COMMENT '匹配优先级 大者先',
  `enabled`        TINYINT     NOT NULL DEFAULT 1,
  `create_time`    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time`    DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted`        TINYINT     NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_tenant_match` (`tenant_id`, `enabled`, `ticket_type`, `device_type`, `factory`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='派发规则';

DROP TABLE IF EXISTS `wo_mock_config`;
CREATE TABLE `wo_mock_config` (
  `id`              BIGINT        NOT NULL,
  `tenant_id`       BIGINT        NOT NULL DEFAULT 1 COMMENT '租户ID',
  `metric_name`     VARCHAR(64)   NOT NULL COMMENT '指标名 AOI_DEFECT_RATE/SPC_CPK/DEVICE_TEMP',
  `factory`         VARCHAR(32)   NOT NULL COMMENT '厂区',
  `scene_name`      VARCHAR(64)   DEFAULT NULL COMMENT '场景',
  `threshold`       DECIMAL(10,4) NOT NULL COMMENT '阈值',
  `compare`         VARCHAR(8)    NOT NULL DEFAULT 'GT' COMMENT 'GT/LT',
  `ticket_type`     VARCHAR(32)   NOT NULL DEFAULT '系统异常' COMMENT '建单映射工单类型',
  `device_type`     VARCHAR(64)   DEFAULT NULL COMMENT '建单映射设备类型',
  `mean`            DECIMAL(10,4) DEFAULT NULL COMMENT '模拟均值',
  `stddev`          DECIMAL(10,4) DEFAULT NULL COMMENT '模拟方差',
  `interval_seconds` INT          NOT NULL DEFAULT 10 COMMENT '采样间隔秒',
  `enabled`         TINYINT       NOT NULL DEFAULT 0,
  `create_time`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time`     DATETIME      NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted`         TINYINT       NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_tenant_metric` (`tenant_id`, `metric_name`, `enabled`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='数据模拟与自动建单配置';

-- ---------------------------------------------------------------------
-- 5. 工单域种子数据：派发规则（F1 厂 设备异常 → 佚名工程师占位由用户表补）
--    默认值班人由配置 tims.order.default-handler 指定（M2 批二）
-- ---------------------------------------------------------------------
INSERT INTO `wo_dispatch_rule` (`id`, `tenant_id`, `ticket_type`, `device_type`, `factory`, `target_user_id`, `priority`) VALUES
(1, 1, '设备异常', '贴片机', 'F1', 1, 30),
(2, 1, '系统异常', '*',        'F1', 1, 20),
(3, 1, '*',        '*',        '*',  1, 1);

INSERT INTO `wo_mock_config` (`id`, `tenant_id`, `metric_name`, `factory`, `scene_name`, `threshold`, `compare`, `ticket_type`, `device_type`, `mean`, `stddev`, `interval_seconds`, `enabled`) VALUES
(1, 1, 'AOI_DEFECT_RATE', 'F1', 'Cell',  0.0200, 'GT', '品质异常', 'AOI检测机', 0.0100, 0.0030, 10, 0),
(2, 1, 'SPC_CPK',         'F1', 'Array', 1.3300, 'LT', '品质异常', '涂布机',    1.5000, 0.1000, 10, 0),
(3, 1, 'DEVICE_TEMP',      'F1', 'Cell',  80.0000, 'GT', '设备异常', '贴合机',   65.0000, 5.0000, 10, 0);
