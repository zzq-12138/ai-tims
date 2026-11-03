<template>
  <div class="assistant-page">
    <el-card shadow="never" class="chat-card">
      <template #header>
        <div class="chat-head">
          <div>
            <span class="chat-title">AI 工单助手</span>
            <span class="muted">工具调用：查工单状态 / 检索知识库 / 工单统计</span>
          </div>
          <el-button size="small" @click="reset">新建对话</el-button>
        </div>
      </template>

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
              <span>{{ m.latencyMs }}ms</span>
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
    </el-card>

    <el-card shadow="never" class="obs-card">
      <template #header>
        <div class="chat-head">
          <span class="chat-title">调用观测</span>
          <el-button size="small" text type="primary" @click="loadUsage">刷新</el-button>
        </div>
      </template>
      <div v-if="summary" class="obs-summary">
        <div class="obs-item"><b>{{ summary.calls ?? 0 }}</b><span>调用次数</span></div>
        <div class="obs-item"><b>{{ summary.totalTokens ?? 0 }}</b><span>总 tokens</span></div>
        <div class="obs-item"><b>{{ summary.toolCalls ?? 0 }}</b><span>工具调用</span></div>
        <div class="obs-item"><b>{{ summary.errorCalls ?? 0 }}</b><span>失败</span></div>
      </div>
      <el-alert title="token 累计用于估算智谱 ¥18 配额余量" type="info" :closable="false" class="mt8" />
      <el-table :data="rows" size="small" border height="calc(100vh - 430px)" class="mt8">
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
import { ElMessage } from 'element-plus'
import { assistantChat, usageRecent, usageSummary } from '../api/ai'

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

function reset() {
  messages.value = []
  input.value = ''
}

async function scrollBottom() {
  await nextTick()
  const el = msgRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function send(text) {
  const content = (text ?? input.value).trim()
  if (!content || loading.value) return
  input.value = ''
  const history = messages.value.map((m) => ({ role: m.role, content: m.content }))
  messages.value.push({ role: 'user', content })
  loading.value = true
  scrollBottom()
  try {
    const data = await assistantChat({ message: content, history })
    messages.value.push({
      role: 'assistant',
      content: data.answer,
      toolCalls: data.toolCalls || [],
      usage: data.usage,
      model: data.model,
      latencyMs: data.latencyMs,
      degraded: data.degraded
    })
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

function fmtTime(v) {
  if (!v) return '-'
  if (Array.isArray(v)) {
    const [y, mo, d, h, mi, s] = v
    return `${y}-${String(mo).padStart(2, '0')}-${String(d).padStart(2, '0')} ${String(h).padStart(2, '0')}:${String(mi).padStart(2, '0')}:${String(s || 0).padStart(2, '0')}`
  }
  return String(v).replace('T', ' ').slice(0, 19)
}

onMounted(loadUsage)
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
.muted { color: #909399; font-size: 12px; }
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
.tool-ms { color: #909399; font-size: 12px; margin-left: 8px; }
.tool-args { color: #606266; font-size: 12px; word-break: break-all; margin-top: 4px; }
.tool-summary { color: #909399; font-size: 12px; margin-top: 2px; }
.msg-meta { display: flex; gap: 12px; align-items: center; color: #909399; font-size: 12px; margin-top: 8px; }
.typing { padding: 6px 4px; }
.composer { display: flex; gap: 10px; align-items: flex-end; border-top: 1px solid #ebeef5; padding-top: 12px; margin-top: 10px; }
.composer .el-input { flex: 1; }
.obs-summary { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; }
.obs-item { background: #f8fafc; border-radius: 6px; padding: 10px; display: flex; flex-direction: column; }
.obs-item b { font-size: 18px; color: #409eff; }
.obs-item span { font-size: 12px; color: #909399; }
.mt8 { margin-top: 8px; }
@media (max-width: 1200px) {
  .assistant-page { grid-template-columns: 1fr; height: auto; }
  .obs-card { height: 520px; }
}
</style>
