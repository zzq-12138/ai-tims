import request from '../utils/request'
import { useAuthStore } from '../stores/auth'

/**
 * M5 AI 接口。
 * 流式接口用 fetch + ReadableStream 手写 SSE 解析：EventSource 无法带 Authorization 头。
 */
export function chatStream(body, handlers = {}, signal) {
  const auth = useAuthStore()
  const headers = { 'Content-Type': 'application/json', Accept: 'text/event-stream' }
  if (auth.token) headers.Authorization = auth.token

  return fetch('/api/ai/chat/stream', {
    method: 'POST',
    headers,
    body: JSON.stringify(body),
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
  return request.post('/api/ai/chat', body, { timeout: 120000 })
}

export function assistantChat(body) {
  return request.post('/api/ai/assistant', body, { timeout: 180000 })
}

export function usageRecent(limit = 20) {
  return request.get('/api/ai/usage/recent', { params: { limit } })
}

export function usageSummary() {
  return request.get('/api/ai/usage/summary')
}
