import request from '../utils/request'

// 工单核心（M2）
export function createTicket(data) {
  return request.post('/api/order/ticket', data)
}

export function pageTickets(params) {
  return request.get('/api/order/ticket/page', { params })
}

export function getTicket(id) {
  return request.get(`/api/order/ticket/${id}`)
}

export function ticketAction(id, action, data) {
  return request.post(`/api/order/ticket/${id}/${action}`, data || {})
}

export function getTimeline(id) {
  return request.get(`/api/order/ticket/${id}/timeline`)
}

export function getSimilar(id) {
  return request.get(`/api/order/ticket/${id}/similar`)
}

export function addComment(ticketId, content) {
  return request.post(`/api/order/comment/${ticketId}`, { content })
}

// 附件（M3 前置补齐）
export function listAttachments(ticketId) {
  return request.get(`/api/order/ticket/${ticketId}/attachment`)
}

export function uploadAttachment(ticketId, file) {
  const fd = new FormData()
  fd.append('file', file)
  return request.post(`/api/order/ticket/${ticketId}/attachment`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' }
  })
}

export function downloadAttachment(ticketId, aid) {
  // blob 直通响应拦截器，由调用方触发浏览器保存
  return request.get(`/api/order/ticket/${ticketId}/attachment/${aid}`, { responseType: 'blob' })
}

export function deleteAttachment(ticketId, aid) {
  return request.delete(`/api/order/ticket/${ticketId}/attachment/${aid}`)
}

// 数据模拟
export function mockBatch(count, factory) {
  return request.post('/api/order/mock/batch', { count, factory })
}

export function statOverview() {
  return request.get('/api/order/stat/overview')
}
