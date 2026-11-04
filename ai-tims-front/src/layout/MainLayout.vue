<template>
  <el-container class="layout">
    <el-aside width="200px" class="aside">
      <div class="logo">AI-TIMS</div>
      <el-menu :default-active="route.path" router background-color="#1f2d3d"
               text-color="#cfd8e3" active-text-color="#409eff">
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
          <span class="user">{{ auth.user?.nickname || '用户' }}</span>
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
.layout { height: 100vh; }
.aside { background-color: #1f2d3d; }
.logo {
  height: 56px;
  line-height: 56px;
  text-align: center;
  color: #fff;
  font-weight: 600;
  letter-spacing: 2px;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e4e7ed;
}
.header-left { display: flex; align-items: center; gap: 12px; }
.ws-tag { cursor: pointer; }
.user { cursor: pointer; }
.card-head { display: flex; align-items: center; gap: 8px; }
.card-title { font-weight: 600; }
.card-meta { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.card-time { color: #909399; font-size: 12px; }
.card-notice { margin-bottom: 8px; }
.kb-item { border-top: 1px dashed #ebeef5; padding: 8px 0; }
.kb-title { font-weight: 600; font-size: 13px; }
.kb-summary { color: #606266; font-size: 12px; margin: 4px 0; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }
.kb-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.kb-empty { color: #909399; font-size: 12px; }
</style>
