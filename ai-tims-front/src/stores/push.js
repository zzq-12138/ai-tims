// 推送消息箱：消息与连接状态分离，消息读态/清空持久化到本机（按用户隔离）
// 存储取舍：只存消息摘要与已读标记，不存 token；localStorage 明文，同源脚本可读，
// 本机演示场景可接受；不对外宣称加密。
import { computed, ref } from 'vue'
import { defineStore } from 'pinia'
import { markMessageRead } from '../api/push'

const MAX_MESSAGES = 50
const MAX_DISMISSED = 200
// 旧版本拿不到用户 id 时把消息写在这个键下；修复后迁到当前用户名下并删除，避免跨账号串数据
const LEGACY_ANON = 'anon'

function keyOf(uid, suffix) {
  return `tims_push_${suffix}_${uid || LEGACY_ANON}`
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
  // 首次装载标记：userId 初始为 ''，若只比较 userId 会在 undefined 场景下直接 return，
  // 导致已读消息永远不落回列表（问题 6 的根因）
  let loaded = false

  const unreadCount = computed(() => messages.value.filter((m) => !m.read).length)

  function persist() {
    localStorage.setItem(keyOf(userId.value, 'inbox'), JSON.stringify(messages.value))
    localStorage.setItem(keyOf(userId.value, 'dismissed'), JSON.stringify(dismissed.value))
  }

  /** 切换账号时按用户装载本机消息箱（首次调用也必须真正读取 localStorage） */
  function loadForUser(uid) {
    const next = String(uid || '')
    if (loaded && next === userId.value) return
    loaded = true
    userId.value = next

    let inbox = readJSON(keyOf(next, 'inbox'), [])
    let dismissed = readJSON(keyOf(next, 'dismissed'), [])

    // 历史数据迁移：旧版本因取错字段（id 而非 userId）把消息写在 anon 键；
    // 仅当当前用户箱为空时接管，接管后删除旧键，避免另一个账号再次读到
    const legacyKey = keyOf(LEGACY_ANON, 'inbox')
    if (next && next !== LEGACY_ANON && inbox.length === 0) {
      const legacy = readJSON(legacyKey, [])
      if (Array.isArray(legacy) && legacy.length) {
        inbox = legacy
        dismissed = readJSON(keyOf(LEGACY_ANON, 'dismissed'), [])
        localStorage.removeItem(legacyKey)
        localStorage.removeItem(keyOf(LEGACY_ANON, 'dismissed'))
      }
    }

    messages.value = Array.isArray(inbox) ? inbox : []
    dismissed.value = Array.isArray(dismissed) ? dismissed : []
    persist()
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

  /** 标为已读：只在原记录上改 read 标记，消息本身仍留在列表（不删除） */
  function markRead(id) {
    const m = messages.value.find((x) => x.id === id)
    if (!m || m.read) return
    m.read = true
    persist()
    if (m.messageId) markMessageRead(m.messageId).catch(() => {})
  }

  /** 全部标为已读：同上，消息保留并灰化，未读数归零 */
  function markAllRead() {
    const pending = messages.value.filter((m) => !m.read)
    pending.forEach((m) => { m.read = true })
    persist()
    pending.filter((m) => m.messageId).forEach((m) => markMessageRead(m.messageId).catch(() => {}))
  }

  /** 清空消息箱：唯一真正移除消息的入口；记入 dismissed 防止重连补推回灌 */
  function clearAll() {
    dismissed.value = [...new Set([...dismissed.value, ...messages.value.map((m) => m.id)])]
    if (dismissed.value.length > MAX_DISMISSED) dismissed.value = dismissed.value.slice(-MAX_DISMISSED)
    messages.value = []
    persist()
  }

  return { messages, dismissed, userId, unreadCount, loadForUser, addCard, addNotice, markRead, markAllRead, clearAll }
})
