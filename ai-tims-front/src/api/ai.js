import request from '../utils/request'
import { useAuthStore } from '../stores/auth'
import { getChatSessionId } from '../utils/chatSession'

/**
 * M5 AI 接口。
 * 流式接口用 fetch + ReadableStream 手写 SSE 解析：EventSource 无法带 Authorization 头。
 */
export function chatStream(body, handlers = {}, signal) {
  const auth = useAuthStore()
  const headers = { 'Content-Type': 'application/json', Accept: 'text/event-stream' }
  if (auth.token) headers.Authorization = auth.token
  const payload = { ...(body || {}), sessionId: (body && body.sessionId) || getChatSessionId() }

  return fetch('/api/ai/chat/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify(payload),
    signal
  }).then(async (res) => {
    if (!res.ok) throw new Error(`AI 接口 HTTP ${res.status}`)
    if (!res.body) throw new Error('当前浏览器不支持流式响应')
    const reader = res.body.getReader()
    const decoder = new TextDecoder('utf-8')
    let buf = ''
    let event = 'message'
    let dataLines = []

    const dispatch = () => {
      if (!dataLines.length) return
      let payload
      try {
        payload = JSON.parse(dataLines.join('\n'))
      } catch (e) {
        payload = dataLines.join('\n')
      }
      const fn = handlers[event]
      if (typeof fn === 'function') fn(payload)
      event = 'message'
      dataLines = []
    }

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      buf += decoder.decode(value, { stream: true }).replace(/\r/g, '')
      let idx
      while ((idx = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, idx)
        buf = buf.slice(idx + 1)
        if (line === '') {
          dispatch()
        } else if (line.startsWith('event:')) {
          event = line.slice(6).trim()
        } else if (line.startsWith('data:')) {
          dataLines.push(line.slice(5).trim())
        }
      }
    }
    dispatch()
  })
}

export function chatSync(body) {
  const payload = { ...(body || {}), sessionId: (body && body.sessionId) || getChatSessionId() }
  return request.post('/api/ai/chat', payload, { timeout: 120000 })
}

export function assistantChat(body) {
  return request.post('/api/ai/assistant', body, { timeout: 180000 })
}

/** C 档兜底建议：回填工单实际处置（只记录配对，不触发入库或反馈闭环） */
export function backfillFallback(id, actualDisposition) {
  return request.post(`/api/ai/fallback/${id}/disposition`, { actualDisposition })
}

export function usageRecent(limit = 20) {
  return request.get('/api/ai/usage/recent', { params: { limit } })
}

export function usageSummary() {
  return request.get('/api/ai/usage/summary')
}

/* ===== M6 问题8：工单助手会话（持久化 / 切换 / 重命名 / 删除） ===== */

export function listSessions() {
  return request.get('/api/ai/chat/sessions')
}

export function createSession(title) {
  return request.post('/api/ai/chat/sessions', { title })
}

export function renameSession(id, title) {
  return request.put(`/api/ai/chat/sessions/${id}`, { title })
}

export function deleteSession(id) {
  return request.delete(`/api/ai/chat/sessions/${id}`)
}

export function sessionMessages(id) {
  return request.get(`/api/ai/chat/sessions/${id}/messages`)
}

/** 撤回前置信息：会删哪些消息、这轮调过哪些工具、是否含写操作 */
export function messageRecallInfo(sessionId, messageId) {
  return request.get(`/api/ai/chat/sessions/${sessionId}/messages/${messageId}/recall-info`)
}

/** 撤回（物理删除该条用户消息 + 它触发的那条 AI 回复）；含写操作时需 force=true */
export function deleteChatMessage(sessionId, messageId, force = false) {
  return request.delete(`/api/ai/chat/sessions/${sessionId}/messages/${messageId}`, {
    params: { force }
  })
}
