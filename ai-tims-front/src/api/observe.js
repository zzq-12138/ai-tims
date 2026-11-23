import request from '../utils/request'

/* ===== 可观测性（观测面板 / 单条详情 / prompt 版本） ===== */

export function observeOverview(params) {
  return request.get('/api/ai/observe/overview', { params })
}

export function observeCalls(params) {
  return request.get('/api/ai/observe/calls', { params })
}

export function observeCallDetail(id) {
  return request.get(`/api/ai/observe/calls/${id}`)
}

export function observePrompts(scene) {
  return request.get('/api/ai/observe/prompts', { params: { scene } })
}

export function observePrompt(id) {
  return request.get(`/api/ai/observe/prompts/${id}`)
}

export function archivePrompt(body) {
  return request.post('/api/ai/observe/prompts', body)
}

/* ===== 管理员：租户 API Key / 额度 / 审计 / 余额（本地估算） ===== */

export function listApiKeys() {
  return request.get('/api/ai/admin/keys')
}

export function saveApiKey(body) {
  return request.post('/api/ai/admin/keys', body)
}

export function deleteApiKey(id) {
  return request.delete(`/api/ai/admin/keys/${id}`)
}

export function revealApiKey(id) {
  return request.get(`/api/ai/admin/keys/${id}/reveal`)
}

export function getQuota() {
  return request.get('/api/ai/admin/keys/quota')
}

export function setQuota(quotaCny) {
  return request.put('/api/ai/admin/keys/quota', { quotaCny })
}

export function keyAudits(limit = 50) {
  return request.get('/api/ai/admin/keys/audits', { params: { limit } })
}

export function keyBalance() {
  return request.get('/api/ai/admin/keys/balance')
}
