// WS 推送客户端：自动重连（指数退避 1s→30s）、10s 心跳、连接诊断指标、事件订阅
// 状态（连接/心跳/重连）与消息（卡片/通知）分离：本文件只负责连接状态，不持有消息列表。
import { ref } from 'vue'

export const HEARTBEAT_MS = 10000

export const wsStatus = ref('OFF') // OFF / CONNECTING / ONLINE / RECONNECT
export const wsReconnectCount = ref(0) // 本次页面会话累计重连次数
export const wsConnectedAt = ref(0) // 最近一次连接成功时间戳
export const wsLastBeatAt = ref(0) // 最近一次心跳（PONG）时间戳
export const wsLastMessageAt = ref(0) // 最近一条业务消息时间戳
export const wsLastDownAt = ref(0) // 最近一次断开时间戳

let socket = null
let heartbeatTimer = null
let retryTimer = null // 重连定时器单例：同时只允许一个排队中的重连
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

function startHeartbeat(ws) {
  stopHeartbeat()
  heartbeatTimer = setInterval(() => {
    // 只给当前活着的这一条连接发心跳，旧连接的定时器不能误发到新连接
    if (socket === ws && ws.readyState === 1) ws.send(JSON.stringify({ type: 'PING' }))
  }, HEARTBEAT_MS)
}

function stopHeartbeat() {
  if (heartbeatTimer) { clearInterval(heartbeatTimer); heartbeatTimer = null }
}

function scheduleReconnect() {
  if (closedByUser || retryTimer) return // 已有排队中的重连则忽略，防止叠出多条连接
  wsStatus.value = 'RECONNECT'
  wsReconnectCount.value += 1
  retryTimer = setTimeout(() => {
    retryTimer = null
    connect()
  }, retryDelay)
  retryDelay = Math.min(retryDelay * 2, 30000)
}

function resetDiagnostics() {
  wsReconnectCount.value = 0
  wsConnectedAt.value = 0
  wsLastBeatAt.value = 0
  wsLastMessageAt.value = 0
  wsLastDownAt.value = 0
}

export function connect(opts = {}) {
  if (!localStorage.getItem('tims_token')) return
  // 用户手动重连才清零诊断计数；自动重连保留累计值以便查看
  if (opts.manual) resetDiagnostics()
  // 已经连上或正在建连时直接复用：不再把活着的连接关掉再重连（否则会 1s 一次反复闪断）
  if (!opts.manual && socket && (socket.readyState === 0 || socket.readyState === 1)) return
  closedByUser = false
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
  wsStatus.value = 'CONNECTING'

  // 先摘掉旧连接的回调再关它，旧连接的迟到事件就不会影响新连接
  const old = socket
  socket = null
  if (old) {
    old.onopen = null
    old.onmessage = null
    old.onclose = null
    old.onerror = null
    try { old.close() } catch (_) { /* 忽略旧连接关闭异常 */ }
  }

  const ws = new WebSocket(wsUrl())
  socket = ws

  ws.onopen = () => {
    if (socket !== ws) return
    wsStatus.value = 'ONLINE'
    wsConnectedAt.value = Date.now()
    retryDelay = 1000
    startHeartbeat(ws)
  }
  ws.onmessage = (ev) => {
    if (socket !== ws) return
    let msg
    try { msg = JSON.parse(ev.data) } catch (_) { return }
    if (msg.type === 'PONG') {
      wsLastBeatAt.value = Date.now()
      return
    }
    wsLastMessageAt.value = Date.now()
    emit(msg.type, msg.data)
  }
  ws.onclose = () => {
    if (socket !== ws) return // 旧连接的 close 不得触发重连
    socket = null
    stopHeartbeat()
    wsLastDownAt.value = Date.now()
    scheduleReconnect()
  }
  ws.onerror = () => {
    if (socket !== ws) return
    try { ws.close() } catch (_) { /* 已关闭则忽略 */ }
  }
}

export function closePush() {
  closedByUser = true
  if (retryTimer) { clearTimeout(retryTimer); retryTimer = null }
  stopHeartbeat()
  try { socket && socket.close() } catch (_) { /* 忽略 */ }
  socket = null
  wsStatus.value = 'OFF'
}

export function reconnectNow() {
  retryDelay = 1000
  connect({ manual: true })
}

export function onPush(type, fn) {
  ;(handlers[type] = handlers[type] || []).push(fn)
  return () => {
    handlers[type] = (handlers[type] || []).filter((f) => f !== fn)
  }
}
