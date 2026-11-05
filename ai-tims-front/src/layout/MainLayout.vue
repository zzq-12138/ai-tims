<template>
  <el-container class="layout">
    <el-aside width="232px" class="aside">
      <div class="logo">
        <span class="logo-mark">T</span>
        <span class="logo-text">
          <strong>AI-TIMS</strong>
          <small>智能工单 · 知识闭环</small>
        </span>
      </div>
      <el-menu :default-active="route.path" router background-color="transparent"
               text-color="#c8d0d8" active-text-color="#f3e6d8">
        <el-menu-item index="/dashboard">
          <span>工作台</span>
        </el-menu-item>
        <el-menu-item index="/tickets">
          <span>工单管理</span>
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/system/users">
          <span>系统管理</span>
        </el-menu-item>
        <el-menu-item v-if="canViewKb" index="/kb">
          <span>知识库</span>
        </el-menu-item>
        <el-menu-item index="/assistant">
          <span>AI 助手</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="header-left">
          <!-- 状态归状态：连接诊断只在状态面板中展示 -->
          <el-popover v-model:visible="statusVisible" trigger="click" placement="bottom-start" width="300" @show="loadOnline">
            <template #reference>
              <el-tag :type="statusType" size="small" effect="dark" class="ws-tag">
                {{ statusText }}
              </el-tag>
            </template>
            <div class="ws-panel">
              <div class="ws-panel-head">推送连接诊断</div>
              <div class="ws-row"><span>连接状态</span><b>{{ statusText }}</b></div>
              <div class="ws-row"><span>心跳间隔</span><span class="mono">{{ HEARTBEAT_MS / 1000 }}s</span></div>
              <div class="ws-row"><span>最近心跳</span><span class="mono">{{ fmtTime(wsLastBeatAt) }}</span></div>
              <div class="ws-row"><span>最近消息</span><span class="mono">{{ fmtTime(wsLastMessageAt) }}</span></div>
              <div class="ws-row"><span>重连次数</span><span class="mono">{{ wsReconnectCount }}</span></div>
              <div class="ws-row"><span>在线坐席</span><span class="mono">{{ onlineCount }}</span></div>
              <el-button size="small" class="ws-reconnect" @click="onReconnect">重新连接</el-button>
              <div class="ws-hint">这里是连接状态；消息请从「消息中心」查看</div>
            </div>
          </el-popover>
          <!-- 消息归消息：可读列表 + 未读数 -->
          <el-badge :value="push.unreadCount" :max="99" :hidden="!push.unreadCount" class="card-badge">
            <el-button size="small" text @click="drawer = true">消息中心</el-button>
          </el-badge>
        </div>
        <el-dropdown @command="onCommand">
          <span class="user-pill">
            <span class="user-dot" />
            <span class="user">{{ auth.user?.nickname || '用户' }}</span>
          </span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>

    <!-- 消息中心：知识卡片 / 工单关闭通知，支持单条已读、全部已读、清空 -->
    <el-drawer v-model="drawer" size="460px">
      <template #header>
        <div class="drawer-head">
          <span>消息中心</span>
          <el-tag v-if="push.unreadCount" type="danger" size="small" effect="plain">未读 {{ push.unreadCount }}</el-tag>
          <el-tag v-else type="info" size="small" effect="plain">全部已读</el-tag>
        </div>
      </template>

      <div class="msg-toolbar">
        <el-button size="small" :disabled="!push.unreadCount" @click="push.markAllRead()">全部标为已读</el-button>
        <el-popconfirm title="清空全部消息？未读数会归零" width="220" @confirm="push.clearAll()">
          <template #reference>
            <el-button size="small" type="danger" plain :disabled="!push.messages.length">清空消息</el-button>
          </template>
        </el-popconfirm>
        <span class="msg-total">共 {{ push.messages.length }} 条</span>
      </div>

      <el-empty v-if="!push.messages.length" description="暂无消息，新工单的知识卡片会实时出现在这里" />

      <div v-for="m in push.messages" :key="m.id" class="msg-item" :class="{ 'is-read': m.read }">
        <div class="msg-head">
          <span class="msg-dot" />
          <span class="msg-title">{{ m.title }}</span>
          <el-tag v-if="m.offline" type="info" size="small">补推</el-tag>
          <el-tag v-if="m.degraded" type="warning" size="small">已降级</el-tag>
          <span class="msg-spacer" />
          <el-button v-if="!m.read" size="small" link type="primary" @click="push.markRead(m.id)">标为已读</el-button>
        </div>
        <div class="msg-meta">
          <el-tag size="small">{{ m.ticketNo || m.ticketId }}</el-tag>
          <el-tag v-if="m.deviceType && m.deviceType !== 'NOTICE'" size="small" type="info">{{ m.deviceType }}</el-tag>
          <span class="msg-time">{{ fmtCreate(m.createTime) }}</span>
        </div>
        <el-alert v-if="m.notice" :title="m.notice" type="warning" :closable="false" class="msg-notice" />
        <div v-for="it in m.items" :key="it.id" class="kb-item">
          <div class="kb-title">{{ it.title }}</div>
          <div class="kb-summary">{{ it.summary || it.content }}</div>
          <div class="kb-tags">
            <el-tag v-for="t in tagsOf(it)" :key="t" size="small" type="success">{{ t }}</el-tag>
          </div>
        </div>
        <div v-if="m.deviceType === 'NOTICE'" class="msg-body">工单状态变更通知</div>
        <div v-else-if="!m.items.length" class="kb-empty">无推荐知识</div>
      </div>
    </el-drawer>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElMessage, ElNotification } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { logout } from '../api/auth'
import { getOnlineUsers, getUnreadMessages } from '../api/push'
import {
  HEARTBEAT_MS, closePush, connect, onPush, reconnectNow,
  wsConnectedAt, wsLastBeatAt, wsLastMessageAt, wsReconnectCount, wsStatus
} from '../utils/ws'
import { useAuthStore } from '../stores/auth'
import { usePushStore } from '../stores/push'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const push = usePushStore()
const roles = computed(() => auth.user?.roles || [])
const isAdmin = computed(() => roles.value.includes('ADMIN'))
// 知识库对管理员/工程师/审核员开放；报障人仅保留工单相关菜单
const canViewKb = computed(() => ['ADMIN', 'ENGINEER', 'REVIEWER'].some(r => roles.value.includes(r)))

const drawer = ref(false)
const statusVisible = ref(false)
const onlineCount = ref(0)

const statusType = computed(() => ({ ONLINE: 'success', CONNECTING: 'warning', RECONNECT: 'danger', OFF: 'info' }[wsStatus.value] || 'info'))
const statusText = computed(() => ({ ONLINE: '推送在线', CONNECTING: '推送连接中', RECONNECT: '推送断线重连中', OFF: '推送未连接' }[wsStatus.value]))

function fmtTime(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleTimeString('zh-CN', { hour12: false })
}

function fmtCreate(t) {
  if (!t) return ''
  return String(t).replace('T', ' ').replace(/\.\d+$/, '')
}

// 卡片 tags 兼容后端返回的 JSON 字符串与数组两种形态
function tagsOf(item) {
  const raw = item && item.tags
  if (Array.isArray(raw)) return raw.slice(0, 4)
  if (typeof raw === 'string') {
    try {
      const v = JSON.parse(raw)
      if (Array.isArray(v)) return v.slice(0, 4)
    } catch (_) { /* 非 JSON 则按分隔符拆分 */ }
    return raw.split(/[,，|]/).map((s) => s.trim()).filter(Boolean).slice(0, 4)
  }
  return []
}

function pushCard(c) {
  if (!push.addCard(c)) return
  ElNotification({
    title: c.offline ? '知识卡片（离线补推）' : '新工单知识卡片',
    message: `${c.ticketNo} ${c.title}\n命中 ${c.items?.length || 0} 条知识${c.degraded ? '（已降级）' : ''}`,
    type: c.degraded ? 'warning' : 'success',
    duration: 6000,
    onClick: () => { drawer.value = true }
  })
}

// /api/auth/me 返回的是 userId（不是 id）：统一取值，避免消息箱落到 anon 键、REST 兜底永不触发
function uidOf() {
  return auth.user?.userId ?? auth.user?.id
}

function fetchUnread() {
  const uid = uidOf()
  if (!uid) return
  getUnreadMessages(uid).then((list) => (list || []).forEach(pushCard)).catch(() => {})
}

async function loadOnline() {
  try {
    const r = await getOnlineUsers()
    onlineCount.value = r?.count ?? 0
  } catch (_) {
    onlineCount.value = 0
  }
}

function onReconnect() {
  reconnectNow()
  ElMessage.success('已发起重新连接')
}

onMounted(() => {
  if (!auth.isLoggedIn) return
  push.loadForUser(uidOf())
  connect()
  onPush('CARD', pushCard)
  // 上线补推（服务端主动下发）+ REST 兜底拉取
  onPush('UNREAD_CARD', pushCard)
  // 工单关闭通知进入消息箱（不再静默丢弃）
  onPush('TICKET_CLOSED', (d) => {
    const ev = d || {}
    const added = push.addNotice(ev.ticketNo, ev.ticketNo ? `工单 ${ev.ticketNo} 已关闭` : '工单已关闭', ev.ticketId)
    if (added) {
      ElNotification({ title: '工单关闭通知', message: ev.ticketNo || String(ev.ticketId || ''), type: 'info', duration: 5000 })
    }
  })
  fetchUnread()
})

// 切换账号时装载各自的本地消息箱
watch(uidOf, (uid) => {
  if (!uid) return
  push.loadForUser(uid)
  fetchUnread()
})

onUnmounted(() => closePush())

async function onCommand(cmd) {
  if (cmd === 'logout') {
    try { await logout() } catch (_) { /* 忽略登出接口异常，本地照常清理 */ }
    closePush()
    auth.clear()
    // 记住密码的留存由登录页勾选状态决定，退出登录不额外清理
    router.push('/login')
  }
}
</script>

<style scoped>
.layout { height: 100vh; background: var(--paper); }
.aside {
  position: relative;
  background:
    linear-gradient(180deg, rgba(255, 255, 255, .05), transparent 28%),
    linear-gradient(180deg, var(--graphite) 0%, var(--graphite-2) 100%);
  border-right: 1px solid #0c1217;
  overflow: hidden;
}
.aside::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255, 255, 255, .035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, .035) 1px, transparent 1px);
  background-size: 28px 28px;
  mask-image: linear-gradient(180deg, rgba(0, 0, 0, .9), transparent 70%);
}
.logo {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  height: 72px;
  padding: 0 18px;
  border-bottom: 1px solid rgba(255, 255, 255, .08);
}
.logo-mark {
  display: grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 7px;
  background: var(--amber);
  color: #fff;
  font-family: var(--font-display);
  font-size: 18px;
  font-weight: 700;
  box-shadow: 0 0 0 1px rgba(255, 255, 255, .18) inset, 0 8px 18px -10px rgba(180, 90, 30, .9);
}
.logo-text { display: flex; flex-direction: column; line-height: 1.2; }
.logo-text strong { color: #f4efe7; font-size: 16px; letter-spacing: .16em; }
.logo-text small { color: #8d99a3; font-size: 10px; letter-spacing: .12em; margin-top: 3px; }
.aside :deep(.el-menu) { border-right: 0; padding: 12px 10px; counter-reset: nav; }
.aside :deep(.el-menu-item) {
  height: 44px;
  margin: 2px 0;
  border-radius: 7px;
  font-size: 13.5px;
  letter-spacing: .06em;
  transition: background-color .18s ease, color .18s ease;
}
.aside :deep(.el-menu-item::before) {
  counter-increment: nav;
  content: counter(nav, decimal-leading-zero);
  margin-right: 12px;
  font-family: var(--font-mono);
  font-size: 10px;
  color: #8d99a3;
}
.aside :deep(.el-menu-item:hover) { background: rgba(255, 255, 255, .06); color: #fff; }
.aside :deep(.el-menu-item.is-active) {
  background: linear-gradient(90deg, rgba(180, 90, 30, .24), rgba(180, 90, 30, .05));
  box-shadow: 3px 0 0 var(--amber) inset;
  color: #f3e6d8;
}
.aside :deep(.el-menu-item.is-active::before) { color: var(--amber); }
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  height: 64px;
  padding: 0 26px;
  border-bottom: 1px solid var(--line);
  background: rgba(255, 253, 249, .82);
  backdrop-filter: blur(6px);
}
.header-left { display: flex; align-items: center; gap: 12px; }
.ws-tag { cursor: pointer; font-family: var(--font-mono); letter-spacing: .04em; }
.user-pill {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  height: 34px;
  padding: 0 14px 0 10px;
  border: 1px solid var(--line);
  border-radius: 999px;
  background: var(--surface);
  cursor: pointer;
  transition: border-color .18s ease, box-shadow .18s ease;
}
.user-pill:hover { border-color: var(--line-strong); box-shadow: var(--shadow-sm); }
.user-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--teal); box-shadow: 0 0 0 3px rgba(47, 125, 102, .14); }
.user { color: var(--ink); font-weight: 600; font-size: 13px; }

/* ---------- 连接诊断面板 ---------- */
.ws-panel { display: flex; flex-direction: column; gap: 7px; }
.ws-panel-head { font-weight: 600; font-size: 13px; margin-bottom: 2px; }
.ws-row { display: flex; justify-content: space-between; gap: 12px; font-size: 12px; color: var(--muted); }
.ws-row b { color: var(--ink); font-size: 12px; }
.ws-row .mono { font-family: var(--font-mono); color: var(--ink-2); }
.ws-reconnect { margin-top: 8px; width: 100%; }
.ws-hint { margin-top: 4px; font-size: 11px; color: var(--muted); line-height: 1.6; }

/* ---------- 消息中心 ---------- */
.drawer-head { display: flex; align-items: center; gap: 10px; }
.msg-toolbar {
  display: flex;
  align-items: center;
  gap: 8px;
  padding-bottom: 12px;
  margin-bottom: 12px;
  border-bottom: 1px solid var(--line);
}
.msg-total { margin-left: auto; color: var(--muted); font-size: 11.5px; font-family: var(--font-mono); }
.msg-item {
  position: relative;
  padding: 12px 14px;
  margin-bottom: 10px;
  border: 1px solid var(--line);
  border-left: 3px solid var(--amber);
  border-radius: 8px;
  background: var(--surface);
  transition: border-color .18s ease, background-color .18s ease;
}
.msg-item.is-read { border-left-color: var(--line-strong); background: var(--surface-2); }
.msg-item.is-read .msg-title { color: var(--muted); font-weight: 500; }
.msg-head { display: flex; align-items: center; gap: 7px; }
.msg-dot { width: 7px; height: 7px; border-radius: 50%; background: var(--rust); flex: none; }
.msg-item.is-read .msg-dot { background: var(--line-strong); }
.msg-title { font-weight: 600; font-size: 13px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.msg-spacer { flex: 1; }
.msg-meta { display: flex; align-items: center; gap: 8px; margin: 6px 0 4px; padding-left: 14px; }
.msg-time { color: var(--muted); font-family: var(--font-mono); font-size: 11px; }
.msg-notice { margin: 8px 0; }
.msg-body { color: var(--ink-2); font-size: 12px; padding-left: 14px; }
.kb-item { border-top: 1px dashed var(--line); padding: 9px 0 2px; padding-left: 14px; }
.kb-title { font-weight: 600; font-size: 12.5px; }
.kb-summary { color: var(--ink-2); font-size: 12px; margin: 3px 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.kb-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.kb-empty { color: var(--muted); font-size: 12px; padding-left: 14px; }

@media (max-width: 820px) {
  .layout { flex-direction: column; }
  .aside { width: 100% !important; height: auto; flex: none; }
  .logo { height: 52px; }
  .aside :deep(.el-menu) { display: flex; overflow-x: auto; padding: 6px 8px; }
  .aside :deep(.el-menu-item) { flex: 0 0 auto; margin: 0 4px; padding: 0 12px; }
  .aside :deep(.el-menu-item::before) { display: none; }
  .header { height: 50px; padding: 0 14px; }
  .ws-tag { font-size: 11px; }
}
</style>
