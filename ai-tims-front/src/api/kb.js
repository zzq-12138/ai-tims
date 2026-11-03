import request from '../utils/request'

// 知识库（M3）
export function pageKnowledge(params) {
  return request.get('/api/kb/knowledge/page', { params })
}

export function getKnowledge(id) {
  return request.get(`/api/kb/knowledge/${id}`)
}

export function createKnowledge(data) {
  return request.post('/api/kb/knowledge', data)
}

export function updateKnowledge(id, data) {
  return request.put(`/api/kb/knowledge/${id}`, data)
}

export function deleteKnowledge(id) {
  return request.delete(`/api/kb/knowledge/${id}`)
}

export function submitKnowledge(id) {
  return request.post(`/api/kb/knowledge/${id}/submit`)
}

export function publishKnowledge(id) {
  return request.post(`/api/kb/knowledge/${id}/publish`)
}

export function rejectKnowledge(id, reason) {
  return request.post(`/api/kb/knowledge/${id}/reject`, { reason })
}

export function listCategories() {
  return request.get('/api/kb/category')
}

// 检索三模式 VECTOR / KEYWORD / HYBRID（fallback=true 表示 Milvus 不可用已降级）
export function searchKnowledge(params) {
  return request.get('/api/kb/search', { params, timeout: 30000 })
}
