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

// 数据模拟
export function mockBatch(count, factory) {
  return request.post('/api/order/mock/batch', { count, factory })
}

export function statOverview() {
  return request.get('/api/order/stat/overview')
}
