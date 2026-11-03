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
  `version`       INT          NOT NULL DEFAULT 0 COMMENT '乐观锁版本号(状态迁移并发控制,M4)',
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

-- ---------------------------------------------------------------------
-- 4.6 wo_attachment 附件表（2026-11-03 拍板补齐，wo_ 五表扩为六表）
--     防路径穿越：存储名 uuid.ext 由服务端生成，original_name 仅存库
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS `wo_attachment`;
CREATE TABLE `wo_attachment` (
  `id`            BIGINT       NOT NULL COMMENT '主键',
  `tenant_id`     BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID',
  `ticket_id`     BIGINT       NOT NULL COMMENT '工单ID',
  `file_name`     VARCHAR(64)  NOT NULL COMMENT '存储文件名 uuid.ext(服务端生成,防路径穿越)',
  `original_name` VARCHAR(255) NOT NULL COMMENT '原始文件名(仅存库,下载时回显)',
  `storage_key`   VARCHAR(255) NOT NULL COMMENT '存储相对路径 yyyyMM/uuid.ext',
  `size`          BIGINT       NOT NULL COMMENT '文件字节数',
  `mime_type`     VARCHAR(128) NOT NULL COMMENT 'MIME类型',
  `uploader_id`   BIGINT       NOT NULL COMMENT '上传人',
  `create_time`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '上传时间',
  `update_time`   DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted`       TINYINT      NOT NULL DEFAULT 0 COMMENT '逻辑删除(文件保留不回收)',
  PRIMARY KEY (`id`),
  KEY `idx_tenant_ticket` (`tenant_id`, `ticket_id`),
  KEY `idx_tenant_uploader` (`tenant_id`, `uploader_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='工单附件表';

-- ---------------------------------------------------------------------
-- 6. kb_ 知识域（M3，2026-11-03）
--    标签方案拍板：tags 用 JSON 列，不建独立标签表——
--    单租户、标签仅用于过滤/展示，检索主链路在 Milvus 向量 + FULLTEXT 全文；
--    独立标签表需 kb_tag + kb_knowledge_tag 两表两 join，收益不抵成本。
--    Milvus collection kb_knowledge_vec（dim=1024）由服务启动/同步时惰性创建。
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS `kb_category`;
CREATE TABLE `kb_category` (
  `id`            BIGINT      NOT NULL COMMENT '主键',
  `tenant_id`     BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  `category_name` VARCHAR(64) NOT NULL COMMENT '分类名',
  `description`   VARCHAR(255) DEFAULT NULL COMMENT '描述',
  `sort`          INT         NOT NULL DEFAULT 0 COMMENT '排序',
  `create_time`   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time`   DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted`       TINYINT     NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_tenant_sort` (`tenant_id`, `sort`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识分类表';

DROP TABLE IF EXISTS `kb_knowledge`;
CREATE TABLE `kb_knowledge` (
  `id`                BIGINT       NOT NULL COMMENT '主键',
  `tenant_id`         BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID',
  `title`             VARCHAR(128) NOT NULL COMMENT '标题',
  `content`           TEXT         NOT NULL COMMENT '正文(向量化的主文本)',
  `summary`           VARCHAR(512) DEFAULT NULL COMMENT '摘要',
  `tags`              JSON         DEFAULT NULL COMMENT '标签数组，如["贴片机","抛料"]',
  `apply_device_type` VARCHAR(64)  DEFAULT NULL COMMENT '适用设备类型(检索加权维度)',
  `category_id`       BIGINT       DEFAULT NULL COMMENT '分类ID',
  `source_ticket_id`  BIGINT       DEFAULT NULL COMMENT '来源工单ID(工单提炼)',
  `status`            VARCHAR(16)  NOT NULL DEFAULT 'DRAFT' COMMENT '状态 DRAFT/PENDING/PUBLISHED/REJECTED',
  `reject_reason`     VARCHAR(255) DEFAULT NULL COMMENT '驳回原因',
  `version`           INT          NOT NULL DEFAULT 1 COMMENT '版本号(每次编辑+1)',
  `quote_count`       INT          NOT NULL DEFAULT 0 COMMENT '被引用次数',
  `create_by`         BIGINT       DEFAULT NULL COMMENT '创建人',
  `vector_synced_at`  DATETIME     DEFAULT NULL COMMENT '最近一次向量同步时间(NULL=待同步)',
  `create_time`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP,
  `update_time`       DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  `deleted`           TINYINT      NOT NULL DEFAULT 0,
  PRIMARY KEY (`id`),
  KEY `idx_tenant_status_time` (`tenant_id`, `status`, `update_time`),
  KEY `idx_tenant_device` (`tenant_id`, `apply_device_type`),
  KEY `idx_tenant_category` (`tenant_id`, `category_id`),
  FULLTEXT KEY `ft_title_content` (`title`, `content`) WITH PARSER ngram
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='知识点主表';

INSERT INTO `kb_category` (`id`, `tenant_id`, `category_name`, `description`, `sort`) VALUES
(1, 1, '设备维护', '设备异常处理类经验', 1),
(2, 1, '品质分析', '品质异常分析类经验', 2),
(3, 1, '系统运维', 'MES/系统类问题',    3);

-- ---------------------------------------------------------------------
-- 7. ps_ 推送域（M4，2026-11-03）
--    ps_push_latency：四时间戳埋点，一条工单一行（ticket.created 触发创建）：
--      t_created 建单落库 / t_event_sent MQ发出 / t_retrieve_done 检索返回 / t_push_sent WS发出
--    degraded 位标记：1=kb关键词降级 2=MQ降级(本地线程池) 4=kb全不可用(空卡片)，按位或叠加
--    ps_push_message：站内消息（离线坐席补推），上线时按 user_id 补推未读
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS `ps_push_latency`;
CREATE TABLE `ps_push_latency` (
  `id`               BIGINT      NOT NULL COMMENT '主键',
  `tenant_id`        BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  `ticket_id`        BIGINT      NOT NULL COMMENT '工单ID',
  `ticket_no`        VARCHAR(32) DEFAULT NULL COMMENT '工单编号',
  `device_type`      VARCHAR(64) DEFAULT NULL COMMENT '设备类型',
  `t_created`        DATETIME(3) DEFAULT NULL COMMENT '建单落库时间',
  `t_event_sent`     DATETIME(3) DEFAULT NULL COMMENT 'MQ事件发出时间',
  `t_retrieve_done`  DATETIME(3) DEFAULT NULL COMMENT '知识检索返回时间',
  `t_push_sent`      DATETIME(3) DEFAULT NULL COMMENT 'WS推送发出时间',
  `degraded`         INT         NOT NULL DEFAULT 0 COMMENT '降级位标记 1=kb降级 2=MQ降级 4=kb不可用',
  `e2e_ms`           BIGINT      DEFAULT NULL COMMENT '端到端耗时ms(t_push_sent-t_created)',
  `create_time`      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `update_time`      DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_ticket` (`ticket_id`),
  KEY `idx_tenant_created` (`tenant_id`, `t_created`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='推送端到端时延埋点表(四时间戳)';

DROP TABLE IF EXISTS `ps_push_message`;
CREATE TABLE `ps_push_message` (
  `id`           BIGINT       NOT NULL COMMENT '主键',
  `tenant_id`    BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID',
  `ticket_id`    BIGINT       NOT NULL COMMENT '工单ID',
  `user_id`      BIGINT       NOT NULL COMMENT '目标坐席用户ID',
  `msg_type`     VARCHAR(16)  NOT NULL DEFAULT 'CARD' COMMENT '消息类型 CARD/NOTICE',
  `title`        VARCHAR(128) NOT NULL COMMENT '标题',
  `content`      TEXT         COMMENT '内容(知识卡片JSON)',
  `read_flag`    TINYINT      NOT NULL DEFAULT 0 COMMENT '是否已读 0/1',
  `pushed_flag`  TINYINT      NOT NULL DEFAULT 0 COMMENT '是否已补推 0/1',
  `create_time`  DATETIME(3)  NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  `read_time`    DATETIME(3)  DEFAULT NULL COMMENT '阅读时间',
  PRIMARY KEY (`id`),
  KEY `idx_tenant_user_read` (`tenant_id`, `user_id`, `read_flag`),
  KEY `idx_tenant_ticket` (`tenant_id`, `ticket_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='站内消息表(离线补推)';

-- 压测运行摘要（M4 批二，每次压测一行）
DROP TABLE IF EXISTS `pt_stress_run`;
CREATE TABLE `pt_stress_run` (
  `id`             BIGINT      NOT NULL COMMENT '主键',
  `tenant_id`      BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  `run_tag`        VARCHAR(64) NOT NULL COMMENT '运行标识(场景名)',
  `concurrency`    INT         NOT NULL DEFAULT 1 COMMENT '并发数',
  `total`          INT         NOT NULL COMMENT '工单总数',
  `ok_count`       INT         NOT NULL DEFAULT 0 COMMENT '成功建单数',
  `fail_count`     INT         NOT NULL DEFAULT 0 COMMENT '失败数',
  `p50_ms`         BIGINT      DEFAULT NULL COMMENT '端到端P50',
  `p95_ms`         BIGINT      DEFAULT NULL COMMENT '端到端P95',
  `p99_ms`         BIGINT      DEFAULT NULL COMMENT '端到端P99',
  `avg_ms`         BIGINT      DEFAULT NULL COMMENT '端到端均值',
  `seg_event_ms`   BIGINT      DEFAULT NULL COMMENT '建单→MQ发出 均值',
  `seg_retrieve_ms` BIGINT     DEFAULT NULL COMMENT 'MQ→检索返回 均值',
  `seg_push_ms`    BIGINT      DEFAULT NULL COMMENT '检索→WS推送 均值',
  `degraded_count` INT         NOT NULL DEFAULT 0 COMMENT '降级行数',
  `create_time`    DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  PRIMARY KEY (`id`),
  KEY `idx_tenant_tag` (`tenant_id`, `run_tag`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='推送压测运行摘要';

-- ---------------------------------------------------------------------
-- 8. ai_ 调用观测（M5，2026-11-03）
--    ai_call_log：每次 LLM 调用/工具调用落一行，用于估算智谱 ¥18 配额余量
--    scene：CHAT_STREAM / CHAT_SYNC / AGENT / AGENT_TOOL；status：SUCCESS / ERROR / DEGRADED
-- ---------------------------------------------------------------------
DROP TABLE IF EXISTS `ai_call_log`;
CREATE TABLE `ai_call_log` (
  `id`                BIGINT      NOT NULL COMMENT '主键',
  `tenant_id`         BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  `scene`             VARCHAR(24) NOT NULL COMMENT '场景 CHAT_STREAM/CHAT_SYNC/AGENT/AGENT_TOOL',
  `model`             VARCHAR(64) DEFAULT NULL COMMENT '模型名',
  `tool_name`         VARCHAR(64) DEFAULT NULL COMMENT '工具名(scene=AGENT_TOOL)',
  `tool_args`         VARCHAR(512) DEFAULT NULL COMMENT '工具入参摘要',
  `prompt_tokens`     INT         NOT NULL DEFAULT 0 COMMENT '输入 token',
  `completion_tokens` INT         NOT NULL DEFAULT 0 COMMENT '输出 token',
  `total_tokens`      INT         NOT NULL DEFAULT 0 COMMENT '合计 token',
  `reasoning_tokens`  INT         NOT NULL DEFAULT 0 COMMENT '思考 token(推理模型)',
  `latency_ms`        BIGINT      DEFAULT NULL COMMENT '总耗时ms',
  `first_token_ms`    BIGINT      DEFAULT NULL COMMENT '首Token耗时ms/工具耗时ms',
  `ref_count`         INT         NOT NULL DEFAULT 0 COMMENT '引用知识条数',
  `status`            VARCHAR(16) NOT NULL DEFAULT 'SUCCESS' COMMENT 'SUCCESS/ERROR/DEGRADED',
  `degraded`          TINYINT     NOT NULL DEFAULT 0 COMMENT '是否降级 0/1',
  `error_msg`         VARCHAR(255) DEFAULT NULL COMMENT '错误摘要',
  `user_id`           BIGINT      DEFAULT NULL COMMENT '调用用户',
  `create_time`       DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  PRIMARY KEY (`id`),
  KEY `idx_tenant_time` (`tenant_id`, `create_time`),
  KEY `idx_tenant_scene` (`tenant_id`, `scene`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI调用观测表';
