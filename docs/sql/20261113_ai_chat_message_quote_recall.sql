-- AI 助手消息级操作：引用回复（撤回改为物理删除，不需要新增列）
-- 应用方式：mysql -udev -p<mysql_pwd> -D aitims < 20261113_ai_chat_message_quote_recall.sql
-- 说明：撤回不再使用“标记”列，直接删除该轮用户消息 + 由其触发的 AI 回复；
--       本文件只保留引用回复所需的三个字段（引用快照，刷新后引用关系仍在）。

ALTER TABLE ai_chat_message
  ADD COLUMN quoted_message_id BIGINT       DEFAULT NULL COMMENT '引用的原消息ID' AFTER content,
  ADD COLUMN quoted_role       VARCHAR(16)  DEFAULT NULL COMMENT '引用消息角色 user/assistant' AFTER quoted_message_id,
  ADD COLUMN quoted_content    VARCHAR(500) DEFAULT NULL COMMENT '引用内容快照（截断）' AFTER quoted_role;
