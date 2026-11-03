// WS 推送客户端（M4）：自动重连（指数退避 1s→30s）、10s 心跳、断线提示、事件订阅
import { ref } from 'vue'

export const wsStatus = ref('OFF') // OFF / CONNECTING / ONLINE / RECONNECT
let socket = null
let heartbeatTimer = null
let retryDelay = 1000
let closedByUser = false
const handlers = {} // type -> [fn]

function wsUrl() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/push?token=${encodeURIComponent(localStorage.getItem('tims_token') || '')}`
}

function emit(type, data) {
  ;(handlers[type] || []).forEach((fn) => {
    try { fn(data) } catch (e) { console.error('[ws] handler error', e) }
  })
}

function startHeartbeat() {
  stopHeartbeat()
  heartbeatTimer = setInterval(() => {
    if (socket && socket.readyState === 1) socket.send(JSON.stringify({ type: 'PING' }))
  }, 10000)
}

function stopHeartbeat() {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
}

function scheduleReconnect() {
  if (closedByUser) return
  wsStatus.value = 'RECONNECT'
  setTimeout(connect, retryDelay)
  retryDelay = Math.min(retryDelay * 2, 30000)
}

export function connect() {
  if (!localStorage.getItem('tims_token')) return
  closedByUser = false
  wsStatus.value = 'CONNECTING'
  try { socket && socket.close() } catch (_) { /* 忽略旧连接关闭异常 */ }
  socket = new WebSocket(wsUrl())

  socket.onopen = () => {
    wsStatus.value = 'ONLINE'
    retryDelay = 1000
    startHeartbeat()
  }
  socket.onmessage = (ev) => {
    let msg
    try { msg = JSON.parse(ev.data) } catch (_) { return }
    if (msg.type === 'PONG') return
    emit(msg.type, msg.data)
  }
  socket.onclose = () => {
    stopHeartbeat()
    scheduleReconnect()
  }
  socket.onerror = () => {
    try { socket.close() } catch (_) { /* 已关闭则忽略 */ }
  }
}

export function closePush() {
  closedByUser = true
  stopHeartbeat()
  try { socket && socket.close() } catch (_) { /* 忽略 */ }
  socket = null
  wsStatus.value = 'OFF'
}

export function onPush(type, fn) {
  ;(handlers[type] = handlers[type] || []).push(fn)
  return () => {
    handlers[type] = (handlers[type] || []).filter((f) => f !== fn)
  }
}
