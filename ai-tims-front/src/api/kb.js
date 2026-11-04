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

// M6 抽取审核中心（系统只给建议，必须人工确认后才新建/合并/驳回）
export function pageExtraction(params) {
  return request.get('/api/kb/extraction/page', { params })
}

export function getExtraction(id) {
  return request.get(`/api/kb/extraction/${id}`)
}

export function updateExtraction(id, data) {
  return request.put(`/api/kb/extraction/${id}`, data)
}

export function approveExtraction(id) {
  return request.post(`/api/kb/extraction/${id}/approve`)
}

// mode: CONCAT（默认拼接）/ KEEP_ORIGINAL（保留原正文）/ REPLACE（用新内容替换）
export function mergeExtraction(id, targetId, mode = 'CONCAT') {
  return request.post(`/api/kb/extraction/${id}/merge`, { targetId, mode })
}

export function previewMergeExtraction(id, targetId) {
  return request.get(`/api/kb/extraction/preview/${id}`, { params: { targetId } })
}

export function rejectExtraction(id, reason) {
  return request.post(`/api/kb/extraction/${id}/reject`, { reason })
}

export function historyExtraction(knowledgeId) {
  return request.get(`/api/kb/extraction/history/${knowledgeId}`)
}
