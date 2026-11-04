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
          <!-- M4：WS 连接状态指示 -->
          <el-tag :type="statusType" size="small" effect="dark" class="ws-tag" @click="drawer = true">
            {{ statusText }}
          </el-tag>
          <!-- M4：实时知识卡片入口（未读角标） -->
          <el-badge :value="cards.length" :hidden="!cards.length" class="card-badge">
            <el-button size="small" text @click="drawer = true">实时推送</el-button>
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

    <!-- 实时知识卡片侧栏 -->
    <el-drawer v-model="drawer" title="实时知识推送" size="420px">
      <el-empty v-if="!cards.length" description="暂无推送，新工单的知识卡片会实时出现在这里" />
      <el-card v-for="c in cards" :key="c.cardKey" shadow="hover" class="push-card">
        <template #header>
          <div class="card-head">
            <span class="card-title">{{ c.title }}</span>
            <el-tag v-if="c.offline" type="info" size="small">补推</el-tag>
            <el-tag v-if="c.degraded" type="warning" size="small">已降级</el-tag>
          </div>
        </template>
        <div class="card-meta">
          <el-tag size="small">{{ c.ticketNo }}</el-tag>
          <el-tag size="small" type="info">{{ c.deviceType }}</el-tag>
          <span class="card-time">{{ c.createTime }}</span>
        </div>
        <el-alert v-if="c.notice" :title="c.notice" type="warning" :closable="false" class="card-notice" />
        <div v-for="it in c.items" :key="it.id" class="kb-item">
          <div class="kb-title">{{ it.title }}</div>
          <div class="kb-summary">{{ it.summary || it.content }}</div>
          <div class="kb-tags">
            <el-tag v-for="t in (it.tags || []).slice(0, 4)" :key="t" size="small" type="success">{{ t }}</el-tag>
          </div>
        </div>
        <div v-if="!c.items?.length" class="kb-empty">无推荐知识</div>
      </el-card>
    </el-drawer>
  </el-container>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { ElNotification } from 'element-plus'
import { useRoute, useRouter } from 'vue-router'
import { logout } from '../api/auth'
import { getUnreadMessages } from '../api/push'
import { connect, closePush, onPush, wsStatus } from '../utils/ws'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const roles = computed(() => auth.user?.roles || [])
const isAdmin = computed(() => roles.value.includes('ADMIN'))
// 知识库对管理员/工程师/审核员开放；报障人仅保留工单相关菜单
const canViewKb = computed(() => ['ADMIN', 'ENGINEER', 'REVIEWER'].some(r => roles.value.includes(r)))

const drawer = ref(false)
const cards = ref([])

const statusType = computed(() => ({ ONLINE: 'success', CONNECTING: 'warning', RECONNECT: 'danger', OFF: 'info' }[wsStatus.value] || 'info'))
const statusText = computed(() => ({ ONLINE: '推送在线', CONNECTING: '推送连接中', RECONNECT: '推送断线重连中', OFF: '推送未连接' }[wsStatus.value]))

function cardKey(c) {
  return `${c.messageId || ''}-${c.ticketId}-${c.createTime}`
}

function pushCard(c) {
  if (!c || cards.value.some((x) => cardKey(x) === cardKey(c))) return
  cards.value.unshift(c)
  if (cards.value.length > 50) cards.value.pop()
  ElNotification({
    title: c.offline ? '知识卡片（离线补推）' : '新工单知识卡片',
    message: `${c.ticketNo} ${c.title}\n命中 ${c.items?.length || 0} 条知识${c.degraded ? '（已降级）' : ''}`,
    type: c.degraded ? 'warning' : 'success',
    duration: 6000,
    onClick: () => { drawer.value = true }
  })
}

onMounted(() => {
  if (!auth.isLoggedIn) return
  connect()
  // 实时卡片
  onPush('CARD', pushCard)
  // 上线补推（服务端主动下发）+ REST 兜底拉取
  onPush('UNREAD_CARD', pushCard)
  // 工单关闭通知
  onPush('TICKET_CLOSED', () => {})
})

// 站内信 REST 兜底（进入布局时拉一次未读）
watch(() => auth.isLoggedIn, (v) => {
  if (!v) return
  connect()
  const uid = auth.user?.id
  if (uid) {
    getUnreadMessages(uid).then((list) => (list || []).forEach(pushCard)).catch(() => {})
  }
}, { immediate: false })

onUnmounted(() => closePush())

async function onCommand(cmd) {
  if (cmd === 'logout') {
    try { await logout() } catch (_) { /* 忽略登出接口异常，本地照常清理 */ }
    closePush()
    auth.clear()
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
  color: #5f6b76;
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
.card-head { display: flex; align-items: center; gap: 8px; }
.card-title { font-weight: 600; }
.card-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.card-time { color: var(--muted); font-family: var(--font-mono); font-size: 11px; }
.card-notice { margin-bottom: 8px; }
.kb-item { border-top: 1px dashed var(--line); padding: 10px 0; }
.kb-title { font-weight: 600; font-size: 13px; }
.kb-summary { color: var(--ink-2); font-size: 12px; margin: 4px 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.kb-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.kb-empty { color: var(--muted); font-size: 12px; }

@media (max-width: 820px) {
  .layout { flex-direction: column; }
  .aside { width: 100% !important; height: auto; flex: none; }
  .logo { height: 52px; }
  .aside :deep(.el-menu) { display: flex; overflow-x: auto; padding: 6px 8px; }
  .aside :deep(.el-menu-item) { flex: 0 0 auto; margin: 0 4px; padding: 0 12px; }
  .aside :deep(.el-menu-item::before) { display: none; }
  .header { height: 50px; padding: 0 14px; }
}
</style>
