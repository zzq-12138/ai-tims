/**
 * 当前问答会话 ID：同一页面生命周期内复用，刷新页面即视为新会话。
 * 仅存内存，不写入 localStorage，也不作为持久化用户标识。
 */
let sessionId = ''

function uuid() {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 'sess-' + Date.now().toString(36) + '-' + Math.random().toString(16).slice(2, 10)
}

export function getChatSessionId() {
  if (!sessionId) sessionId = uuid()
  return sessionId
}
