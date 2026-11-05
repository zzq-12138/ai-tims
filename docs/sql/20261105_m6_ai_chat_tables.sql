-- M6 问题8：AI 工单助手会话与消息（最小新增，不改动既有表）
-- 应用方式：mysql -udev -p<mysql_pwd> -D aitims < 20261105_m6_ai_chat_tables.sql
-- 隔离维度：tenant_id + user_id；删除会话为软删（deleted=1），消息保留备查。

CREATE TABLE IF NOT EXISTS ai_chat_session (
  id          BIGINT       NOT NULL AUTO_INCREMENT COMMENT '会话ID',
  tenant_id   BIGINT       NOT NULL DEFAULT 1 COMMENT '租户ID',
  user_id     BIGINT       NOT NULL COMMENT '用户ID',
  title       VARCHAR(100) NOT NULL DEFAULT '新会话' COMMENT '会话标题（首条用户消息自动命名）',
  create_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  update_time DATETIME     NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '最近活跃时间',
  deleted     TINYINT      NOT NULL DEFAULT 0 COMMENT '0正常 1软删',
  PRIMARY KEY (id),
  KEY idx_ai_session_owner (tenant_id, user_id, deleted, update_time)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI工单助手会话';

CREATE TABLE IF NOT EXISTS ai_chat_message (
  id          BIGINT      NOT NULL AUTO_INCREMENT COMMENT '消息ID',
  session_id  BIGINT      NOT NULL COMMENT '会话ID',
  tenant_id   BIGINT      NOT NULL DEFAULT 1 COMMENT '租户ID',
  user_id     BIGINT      NOT NULL COMMENT '用户ID',
  role        VARCHAR(16) NOT NULL COMMENT 'user / assistant',
  content     MEDIUMTEXT  NOT NULL COMMENT '消息正文',
  model       VARCHAR(64) DEFAULT NULL COMMENT '模型名（assistant 消息）',
  tool_calls  MEDIUMTEXT  DEFAULT NULL COMMENT '工具调用明细 JSON',
  usage_json  VARCHAR(255) DEFAULT NULL COMMENT 'token 用量 JSON',
  create_time DATETIME    NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
  PRIMARY KEY (id),
  KEY idx_ai_msg_session (session_id, id),
  KEY idx_ai_msg_owner (tenant_id, user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='AI工单助手消息';
