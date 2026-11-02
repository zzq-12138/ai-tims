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
  `phone`       VARCHAR(16)  DEFAULT NULL COMMENT '手机号',
  `email`       VARCHAR(64)  DEFAULT NULL COMMENT '邮箱',
  `status`      TINYINT      NOT NULL DEFAULT 1 COMMENT '1启用 0停用',
  `create_time` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  `update_time` DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  `deleted`     TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_tenant_username` (`tenant_id`, `username`),
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

INSERT INTO `sys_user` (`id`, `tenant_id`, `username`, `password`, `nickname`, `dept_id`, `factory`) VALUES
(1, 1, 'admin', '$2a$10$1Qd7ZqwF9yOKPJ1LvvMcW.RiBpbRlnqA4uIAiSsIbXmw5H.jmMuD2', '系统管理员', 1, 'F1');

INSERT INTO `sys_user_role` (`id`, `tenant_id`, `user_id`, `role_id`) VALUES
(1, 1, 1, 1);
