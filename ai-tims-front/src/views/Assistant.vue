<template>
  <div class="assistant-page">
    <el-card shadow="never" class="chat-card">
      <template #header>
        <div class="chat-head">
          <div>
            <span class="chat-title">AI 工单助手</span>
            <span class="muted">工具调用：查工单状态 / 检索知识库 / 工单统计</span>
          </div>
          <el-button size="small" @click="newSession">新建对话</el-button>
        </div>
      </template>

      <div class="chat-body">
        <!-- 左侧会话列表：新建 / 切换 / 重命名 / 删除；按 tenant+user 隔离 -->
        <aside class="session-pane">
          <div class="session-head">
            <span>历史会话</span>
            <el-button size="small" text class="new-session" @click="newSession">+ 新建</el-button>
          </div>
          <div class="session-scroll">
            <el-empty v-if="!sessions.length" description="暂无会话" :image-size="56" />
            <div v-for="s in sessions" :key="s.id" class="session-item"
                 :class="{ active: String(s.id) === String(sessionId) }" @click="openSession(s)">
              <div class="session-title" :title="s.title">{{ s.title }}</div>
              <div class="session-meta">{{ fmtTime(s.updateTime) }}</div>
              <div class="session-actions">
                <el-button link size="small" class="session-act" @click.stop="renamePrompt(s)">改名</el-button>
                <el-button link size="small" class="session-act danger" @click.stop="removeSession(s)">删除</el-button>
              </div>
            </div>
          </div>
        </aside>

        <div class="chat-main">
          <div class="messages" ref="msgRef">
            <el-empty v-if="!messages.length" description="问我工单进度、故障处理方法或工单统计">
              <div class="quick">
                <el-button v-for="q in quickPrompts" :key="q" size="small" plain @click="send(q)">{{ q }}</el-button>
              </div>
            </el-empty>

            <div v-for="(m, i) in messages" :key="i" :class="['bubble-row', m.role]">
              <div v-if="m.role === 'user'" class="bubble user-bubble">{{ m.content }}</div>
              <div v-else class="bubble ai-bubble">
                <div class="ai-text">{{ m.content || (loading && i === messages.length - 1 ? '思考中…' : '') }}</div>
                <el-collapse v-if="m.toolCalls && m.toolCalls.length" class="tool-collapse">
                  <el-collapse-item :title="`工具调用 ${m.toolCalls.length} 次（点开查看参数/耗时）`">
                    <div v-for="(t, j) in m.toolCalls" :key="j" class="tool-row">
                      <el-tag size="small" :type="t.status === 'OK' ? 'success' : 'danger'">{{ t.name }}</el-tag>
                      <span class="tool-ms">{{ t.elapsedMs }}ms</span>
                      <div class="tool-args">{{ t.args }}</div>
                      <div class="tool-summary">{{ t.summary }}</div>
                    </div>
                  </el-collapse-item>
                </el-collapse>
                <div v-if="m.usage" class="msg-meta">
                  <span>{{ m.model }}</span>
                  <span>tokens {{ m.usage.promptTokens }}+{{ m.usage.completionTokens }}={{ m.usage.totalTokens }}</span>
                  <span v-if="m.latencyMs">{{ m.latencyMs }}ms</span>
                  <el-tag v-if="m.degraded" size="small" type="warning">降级</el-tag>
                </div>
              </div>
            </div>
            <div v-if="loading" class="typing muted">助手正在调用工具并生成回答…</div>
          </div>

          <div class="composer">
            <el-input v-model="input" type="textarea" :rows="2" resize="none"
                      placeholder="例如：工单 WO20261103-2129 现在是什么状态？（Enter 发送，Shift+Enter 换行）"
                      @keydown.enter.exact.prevent="send()" />
            <el-button type="primary" :loading="loading" :disabled="!input.trim()" @click="send()">发送</el-button>
          </div>
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="obs-card">
      <template #header>
        <div class="chat-head">
          <span class="chat-title">调用观测</span>
          <el-button size="small" text type="primary" class="obs-refresh" @click="loadUsage">刷新</el-button>
        </div>
      </template>
      <div v-if="summary" class="obs-summary">
        <div class="obs-item"><b>{{ summary.calls ?? 0 }}</b><span>调用次数</span></div>
        <div class="obs-item"><b>{{ summary.totalTokens ?? 0 }}</b><span>总 tokens</span></div>
        <div class="obs-item"><b>{{ summary.toolCalls ?? 0 }}</b><span>工具调用</span></div>
        <div class="obs-item"><b>{{ summary.errorCalls ?? 0 }}</b><span>失败</span></div>
      </div>

      <div v-if="summary" class="usage-block">
        <div class="usage-head">
          <span class="usage-title">已用 tokens</span>
          <b>{{ fmtNum(summary.totalTokens) }}</b>
          <el-tag size="small" type="info">本地计量 · 估算</el-tag>
        </div>
        <div class="usage-money">
          <span>估算费用 <b>¥{{ fmtMoney(summary.estimatedCostCny) }}</b></span>
          <span>预算 ¥{{ fmtMoney(summary.budgetCny) }} · 剩余 <b>¥{{ fmtMoney(summary.remainingCny) }}</b></span>
        </div>
        <el-progress :percentage="Number(summary.usedPercent) || 0" :stroke-width="8" :show-text="false" />
        <div class="usage-note">
          智谱开放平台未提供余额/额度查询 API（实测 /balance、/usage、/quota 均 404），此处按调用记录 usage 累计、
          按配置单价（输入 ¥{{ summary.priceInputPer1k }}/千、输出 ¥{{ summary.priceOutputPer1k }}/千）折算，非官方余额。
        </div>
      </div>

      <div v-if="summary && summary.daily && summary.daily.length" class="usage-chart">
        <div class="split-title">近 7 天 tokens 走势</div>
        <div class="bars">
          <div v-for="d in summary.daily" :key="d.day" class="bar-col">
            <div class="bar-val">{{ fmtNum(d.tokens) }}</div>
            <div class="bar" :style="{ height: barH(d.tokens) }" />
            <div class="bar-day">{{ String(d.day).slice(5) }}</div>
          </div>
        </div>
      </div>

      <div v-if="summary" class="usage-split">
        <div class="split-col">
          <div class="split-title">按场景</div>
          <div v-for="s in summary.byScene || []" :key="s.scene" class="split-row">
            <span>{{ s.scene }}</span><b>{{ fmtNum(s.tokens) }}</b>
          </div>
        </div>
        <div class="split-col">
          <div class="split-title">按模型</div>
          <div v-for="m in summary.byModel || []" :key="m.model" class="split-row">
            <span>{{ m.model }}</span><b>{{ fmtNum(m.tokens) }}</b>
          </div>
        </div>
      </div>

      <el-table :data="rows" size="small" border height="200" class="mt8">
        <el-table-column label="时间" width="150">
          <template #default="{ row }">{{ fmtTime(row.createTime) }}</template>
        </el-table-column>
        <el-table-column label="场景" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="row.scene === 'AGENT_TOOL' ? 'warning' : 'primary'">{{ row.scene }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="明细" min-width="140">
          <template #default="{ row }">
            <span v-if="row.toolName">{{ row.toolName }}</span>
            <span v-else>{{ row.model }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="totalTokens" label="tokens" width="80" />
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">
            <span v-if="row.latencyMs">{{ row.latencyMs }}ms</span>
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="90" />
      </el-table>
    </el-card>
  </div>
</template>

<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  assistantChat, createSession, deleteSession, listSessions, renameSession,
  sessionMessages, usageRecent, usageSummary
} from '../api/ai'

const sessions = ref([])
const sessionId = ref(null)
const sessionTitle = ref('')
const messages = ref([])
const input = ref('')
const loading = ref(false)
const msgRef = ref(null)
const summary = ref(null)
const rows = ref([])

const quickPrompts = [
  '今天待办工单有多少？',
  '贴片机抛料怎么处理？',
  '查询最近工单状态'
]

const LAST_SESSION_KEY = 'ai-chat-last-session'

function parseJson(raw, fallback) {
  if (raw == null || raw === '') return fallback
  if (typeof raw === 'object') return raw
  try {
    return JSON.parse(raw)
  } catch (_) {
    return fallback
  }
}

/** 库内消息 → 气泡（刷新/切会话后恢复完整记录） */
function toBubble(m) {
  return {
    role: m.role,
    content: m.content,
    toolCalls: parseJson(m.toolCalls, []),
    usage: parseJson(m.usageJson, null),
    model: m.model
  }
}

async function scrollBottom() {
  await nextTick()
  const el = msgRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function loadSessions() {
  try {
    const list = (await listSessions()) || []
    sessions.value = list
    if (!list.length) {
      sessionId.value = null
      sessionTitle.value = ''
      messages.value = []
      return
    }
    const stillThere = list.some((s) => String(s.id) === String(sessionId.value))
    if (!stillThere) {
      // 刷新/重新打开时优先恢复上次查看的会话（仅本地导航状态，归属仍由服务端校验）
      const remembered = localStorage.getItem(LAST_SESSION_KEY)
      const target = remembered && list.find((x) => String(x.id) === remembered)
      await openSession(target || list[0])
    }
  } catch (e) {
    // 列表失败不打断当前对话
  }
}

async function openSession(s) {
  if (loading.value) return
  sessionId.value = s.id
  sessionTitle.value = s.title
  localStorage.setItem(LAST_SESSION_KEY, String(s.id))
  try {
    const list = (await sessionMessages(s.id)) || []
    messages.value = list.map(toBubble)
  } catch (e) {
    messages.value = []
    ElMessage.error(e.message || '会话消息加载失败')
  }
  scrollBottom()
}

async function newSession() {
  if (loading.value) return
  try {
    const s = await createSession()
    sessions.value.unshift(s)
    sessionId.value = s.id
    sessionTitle.value = s.title
    messages.value = []
    input.value = ''
  } catch (e) {
    ElMessage.error(e.message || '新建会话失败')
  }
}

async function renamePrompt(s) {
  try {
    const { value } = await ElMessageBox.prompt('输入新的会话名称', '重命名会话', {
      inputValue: s.title,
      confirmButtonText: '保存',
      cancelButtonText: '取消',
      inputValidator: (v) => (v && v.trim() ? true : '名称不能为空')
    })
    const updated = await renameSession(s.id, value.trim())
    s.title = (updated && updated.title) || value.trim()
    if (String(sessionId.value) === String(s.id)) sessionTitle.value = s.title
    ElMessage.success('已重命名')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error((e && e.message) || '重命名失败')
  }
}

async function removeSession(s) {
  try {
    await ElMessageBox.confirm(`删除会话「${s.title}」？删除后消息记录不再展示。`, '删除会话', {
      type: 'warning',
      confirmButtonText: '删除',
      cancelButtonText: '取消'
    })
    await deleteSession(s.id)
    sessions.value = sessions.value.filter((x) => String(x.id) !== String(s.id))
    if (String(sessionId.value) === String(s.id)) {
      sessionId.value = null
      sessionTitle.value = ''
      messages.value = []
      if (sessions.value.length) await openSession(sessions.value[0])
    }
    ElMessage.success('已删除')
  } catch (e) {
    if (e !== 'cancel' && e !== 'close') ElMessage.error((e && e.message) || '删除失败')
  }
}

/** 会话标题/活跃时间变化后置顶（后端已改名时同步） */
function bumpSession(title) {
  const i = sessions.value.findIndex((s) => String(s.id) === String(sessionId.value))
  if (i < 0) return
  const s = sessions.value[i]
  if (title) {
    s.title = title
    sessionTitle.value = title
  }
  s.updateTime = new Date().toISOString()
  sessions.value.splice(i, 1)
  sessions.value.unshift(s)
}

async function send(text) {
  const content = (text ?? input.value).trim()
  if (!content || loading.value) return
  input.value = ''
  if (!sessionId.value) {
    try {
      const s = await createSession()
      sessions.value.unshift(s)
      sessionId.value = s.id
      sessionTitle.value = s.title
    } catch (e) {
      ElMessage.error(e.message || '会话创建失败')
      return
    }
  }
  messages.value.push({ role: 'user', content })
  loading.value = true
  scrollBottom()
  try {
    // 多轮上下文由后端按 sessionId 从 ai_chat_message 取窗口，这里不再回传 history
    const data = await assistantChat({ message: content, sessionId: sessionId.value })
    messages.value.push({
      role: 'assistant',
      content: data.answer,
      toolCalls: data.toolCalls || [],
      usage: data.usage,
      model: data.model,
      latencyMs: data.latencyMs,
      degraded: data.degraded
    })
    bumpSession(data.sessionTitle)
  } catch (e) {
    messages.value.push({ role: 'assistant', content: '调用失败：' + (e.message || '未知错误') })
    ElMessage.error(e.message || 'AI 助手调用失败')
  } finally {
    loading.value = false
    scrollBottom()
    loadUsage()
  }
}

async function loadUsage() {
  try {
    const [s, r] = await Promise.all([usageSummary(), usageRecent(15)])
    summary.value = s
    rows.value = r || []
  } catch (e) {
    // 观测面板失败不打断对话
  }
}

function fmtNum(v) {
  return Number(v || 0).toLocaleString('zh-CN')
}

/** 只做“配置单价 × 实测 token”的折算，页面明确标注估算；不编造余额 */
function fmtMoney(v) {
  return Number(v || 0).toFixed(4)
}

function barH(v) {
  const list = (summary.value && summary.value.daily) || []
  const max = Math.max(...list.map((x) => Number(x.tokens || 0)), 1)
  return Math.max(6, Math.round((Number(v || 0) / max) * 64)) + 'px'
}

function fmtTime(v) {
  if (!v) return '-'
  if (Array.isArray(v)) {
    const [y, mo, d, h, mi, s] = v
    return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')} ${String(h).padStart(2, '0')}:${String(mi).padStart(2, '0')}:${String(s || 0).padStart(2, '0')}`
  }
  return String(v).replace('T', ' ').slice(0, 19)
}

onMounted(async () => {
  await loadSessions()
  loadUsage()
})
</script>

<style scoped>
.assistant-page {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 390px;
  gap: 16px;
  height: calc(100vh - 100px);
}
.chat-card, .obs-card { display: flex; flex-direction: column; height: 100%; }
.chat-card :deep(.el-card__body), .obs-card :deep(.el-card__body) {
  flex: 1; display: flex; flex-direction: column; min-height: 0;
}
.chat-head { display: flex; align-items: center; justify-content: space-between; }
.chat-title { font-weight: 600; margin-right: 10px; }
.muted { color: var(--muted); font-size: 12px; }
.chat-body { flex: 1; display: flex; gap: 14px; min-height: 0; }
.session-pane {
  flex: 0 0 186px; width: 186px; display: flex; flex-direction: column; min-height: 0;
  border-right: 1px dashed var(--line); padding-right: 12px;
}
.session-head { display: flex; align-items: center; justify-content: space-between; padding-bottom: 8px; }
.session-head span { font-size: 12px; color: var(--muted); }
.new-session { color: var(--amber-deep); font-size: 12px; }
.session-scroll { flex: 1; overflow: auto; }
.session-item {
  padding: 7px 9px; margin-bottom: 6px; border-radius: 6px; cursor: pointer;
  border: 1px solid transparent;
}
.session-item:hover { background: var(--amber-soft); }
.session-item.active { background: var(--amber-soft); border-color: var(--line-strong); }
.session-title { font-size: 13px; color: var(--ink); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.session-meta { font-size: 11px; color: var(--muted); margin-top: 2px; }
.session-actions { display: flex; gap: 10px; margin-top: 1px; }
.session-act { padding: 0; height: 18px; font-size: 11px; color: var(--muted); }
.session-act.danger { color: var(--rust); }
.chat-main { flex: 1; display: flex; flex-direction: column; min-width: 0; min-height: 0; }
.messages { flex: 1; overflow: auto; padding-right: 4px; }
.quick { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; max-width: 520px; }
.bubble-row { display: flex; margin: 10px 0; }
.bubble-row.user { justify-content: flex-end; }
.bubble { max-width: 82%; border-radius: 8px; padding: 10px 12px; font-size: 14px; line-height: 1.7; }
.user-bubble { background: #ecf5ff; color: #303133; white-space: pre-wrap; }
.ai-bubble { background: #f6f8fa; color: #303133; }
.ai-text { white-space: pre-wrap; }
.tool-collapse { margin-top: 8px; }
.tool-row { border-top: 1px dashed #e4e7ed; padding: 6px 0; }
.tool-ms { color: var(--muted); font-size: 12px; margin-left: 8px; }
.tool-args { color: #606266; font-size: 12px; word-break: break-all; margin-top: 4px; }
.tool-summary { color: var(--muted); font-size: 12px; margin-top: 2px; }
.msg-meta { display: flex; gap: 12px; align-items: center; color: var(--muted); font-size: 12px; margin-top: 8px; }
.typing { padding: 6px 4px; }
.composer { display: flex; gap: 10px; align-items: flex-end; border-top: 1px solid #ebeef5; padding-top: 12px; margin-top: 10px; }
.composer .el-input { flex: 1; }
.obs-summary { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.obs-item { background: #f8fafc; border-radius: 6px; padding: 10px; display: flex; flex-direction: column; }
.obs-item b { font-size: 18px; color: var(--amber-deep); }
.obs-item span { font-size: 12px; color: var(--muted); }
/* 观测面板“刷新”为小号文字按钮，琥珀色在米白底上只有 4.67:1，压深到 amber-deep（6.76:1） */
.obs-refresh { color: var(--amber-deep); font-weight: 600; }
.obs-refresh:hover { color: var(--ink); background: var(--amber-soft); }
.usage-block { margin-top: 10px; border: 1px solid var(--line); border-radius: 8px; padding: 10px 12px; }
.usage-head { display: flex; align-items: center; gap: 8px; }
.usage-title { font-size: 12px; color: var(--muted); }
.usage-head b { font-size: 18px; color: var(--ink); }
.usage-money { display: flex; justify-content: space-between; gap: 10px; font-size: 12px; color: var(--muted); margin: 8px 0 6px; flex-wrap: wrap; }
.usage-money b { color: var(--amber-deep); }
.usage-note { font-size: 11px; line-height: 1.6; color: var(--muted); margin-top: 8px; }
.usage-chart { margin-top: 10px; }
.bars { display: flex; align-items: flex-end; gap: 12px; height: 92px; padding: 6px 2px 0; }
.bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
.bar { width: 22px; background: linear-gradient(180deg, #c97b42, #8f4616); border-radius: 3px 3px 0 0; }
.bar-val { font-size: 10px; color: var(--muted); }
.bar-day { font-size: 10px; color: var(--muted); margin-top: 3px; }
.usage-split { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 10px; }
.split-col { border: 1px dashed var(--line); border-radius: 6px; padding: 8px 10px; }
.split-title { font-size: 12px; color: var(--muted); margin-bottom: 4px; }
.split-row { display: flex; justify-content: space-between; font-size: 12px; color: var(--ink); padding: 2px 0; }
.split-row b { color: var(--amber-deep); font-weight: 600; }
.obs-card :deep(.el-card__body) { overflow: auto; }
.mt8 { margin-top: 8px; }
@media (max-width: 1200px) {
  .assistant-page { grid-template-columns: 1fr; height: auto; }
  .chat-card { height: 640px; }
  .obs-card { height: 520px; }
}
@media (max-width: 820px) {
  .session-pane { flex-basis: 150px; width: 150px; }
}
</style>
