// 推送消息箱：消息与连接状态分离，消息读态/清空持久化到本机（按用户隔离）
// 存储取舍：只存消息摘要与已读标记，不存 token；localStorage 明文，同源脚本可读，
// 本机演示场景可接受；不对外宣称加密。
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { markMessageRead } from '../api/push'

const MAX_MESSAGES = 50
const MAX_DISMISSED = 200

function keyOf(uid, suffix) {
  return `tims_push_${suffix}_${uid || 'anon'}`
}

function readJSON(k, fallback) {
  try {
    const v = JSON.parse(localStorage.getItem(k) || 'null')
    return v == null ? fallback : v
  } catch (_) {
    return fallback
  }
}

function cardId(c) {
  return `${c.messageId || ''}-${c.ticketId}-${c.createTime}`
}

export const usePushStore = defineStore('push', () => {
  const messages = ref([])
  const dismissed = ref([])
  const userId = ref('')

  const unreadCount = computed(() => messages.value.filter((m) => !m.read).length)

  function persist() {
    localStorage.setItem(keyOf(userId.value, 'inbox'), JSON.stringify(messages.value))
    localStorage.setItem(keyOf(userId.value, 'dismissed'), JSON.stringify(dismissed.value))
  }

  /** 切换账号时按用户装载本机消息箱 */
  function loadForUser(uid) {
    const next = String(uid || '')
    if (next === userId.value) return
    userId.value = next
    messages.value = readJSON(keyOf(next, 'inbox'), [])
    dismissed.value = readJSON(keyOf(next, 'dismissed'), [])
  }

  /** 收到卡片：去重 + 已清空的不再回灌 */
  function addCard(c) {
    if (!c || !c.ticketId) return false
    const id = cardId(c)
    if (dismissed.value.includes(id)) return false
    if (messages.value.some((m) => m.id === id)) return false
    messages.value.unshift({
      id,
      messageId: c.messageId || null,
      ticketId: String(c.ticketId),
      ticketNo: c.ticketNo || '',
      title: c.title || '知识卡片',
      deviceType: c.deviceType || '',
      createTime: c.createTime || '',
      notice: c.notice || '',
      degraded: !!c.degraded,
      offline: !!c.offline,
      items: c.items || [],
      read: false,
      receivedAt: Date.now()
    })
    if (messages.value.length > MAX_MESSAGES) messages.value.length = MAX_MESSAGES
    persist()
    return true
  }

  /** 工单关闭：作为一条轻消息进入消息箱（可选已读） */
  function addNotice(ticketNo, title, ticketId) {
    if (!ticketId) return false
    const id = `closed-${ticketId}`
    if (dismissed.value.includes(id) || messages.value.some((m) => m.id === id)) return false
    messages.value.unshift({
      id,
      messageId: null,
      ticketId: String(ticketId),
      ticketNo: ticketNo || '',
      title: title || `工单 ${ticketNo || ticketId} 已关闭`,
      deviceType: 'NOTICE',
      createTime: '',
      notice: '',
      degraded: false,
      offline: false,
      items: [],
      read: false,
      receivedAt: Date.now()
    })
    if (messages.value.length > MAX_MESSAGES) messages.value.length = MAX_MESSAGES
    persist()
    return true
  }

  function markRead(id) {
    const m = messages.value.find((x) => x.id === id)
    if (!m || m.read) return
    m.read = true
    persist()
    if (m.messageId) markMessageRead(m.messageId).catch(() => {})
  }

  function markAllRead() {
    const pending = messages.value.filter((m) => !m.read)
    pending.forEach((m) => { m.read = true })
    persist()
    pending.filter((m) => m.messageId).forEach((m) => markMessageRead(m.messageId).catch(() => {}))
  }

  /** 清空消息箱：未读数归零；记入 dismissed 防止重连补推回灌 */
  function clearAll() {
    dismissed.value = [...new Set([...dismissed.value, ...messages.value.map((m) => m.id)])]
    if (dismissed.value.length > MAX_DISMISSED) dismissed.value = dismissed.value.slice(-MAX_DISMISSED)
    messages.value = []
    persist()
  }

  return { messages, dismissed, userId, unreadCount, loadForUser, addCard, addNotice, markRead, markAllRead, clearAll }
})
