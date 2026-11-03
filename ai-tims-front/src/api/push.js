// 推送服务 REST API（M4）：统计 / 在线列表 / 未读站内消息
import request from '../utils/request'

// 端到端时延统计（P50/P95/P99 + 分段均值）
export function getPushStats(limit = 200) {
  return request.get('/api/push/stats', { params: { limit } })
}

// 在线坐席列表（在线状态指示）
export function getOnlineUsers() {
  return request.get('/api/push/online')
}

// 未读站内消息（WS 之外的兜底拉取）
export function getUnreadMessages(userId) {
  return request.get('/api/push/messages/unread', { params: { userId } })
}

// 标记站内消息已读
export function markMessageRead(messageId) {
  return request.post('/api/push/messages/read', { messageId })
}
