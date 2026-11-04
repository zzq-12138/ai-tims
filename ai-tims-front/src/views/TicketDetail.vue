<template>
  <div v-if="detail">
    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>{{ detail.ticket.title }}</span>
          <div>
            <el-tag :type="statusType(detail.ticket.status)" class="mr8">{{ statusMap[detail.ticket.status] }}</el-tag>
            <el-button size="small" type="primary" plain class="mr8" @click="openAi">AI 分析</el-button>
            <el-button size="small" @click="$router.back()">返回</el-button>
          </div>
        </div>
      </template>

      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="工单编号"><span class="mono">{{ detail.ticket.ticketNo || '-' }}</span></el-descriptions-item>
        <el-descriptions-item label="类型">{{ detail.ticket.ticketType }}</el-descriptions-item>
        <el-descriptions-item label="紧急程度">{{ { 1: '高', 2: '中', 3: '低' }[detail.ticket.urgency] }}</el-descriptions-item>
        <el-descriptions-item label="厂区/厂别">{{ detail.ticket.factory || '-' }} / {{ detail.ticket.plant || '-' }}</el-descriptions-item>
        <el-descriptions-item label="设备类型">{{ detail.ticket.deviceType || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Glass ID"><span class="mono">{{ detail.ticket.glassId || '-' }}</span></el-descriptions-item>
        <el-descriptions-item label="处理人">{{ detail.ticket.handlerName || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间"><span class="mono">{{ detail.ticket.createTime }}</span></el-descriptions-item>
        <el-descriptions-item label="当前节点">{{ detail.ticket.currentNode }}</el-descriptions-item>
        <el-descriptions-item label="现象描述" :span="3">{{ detail.ticket.description }}</el-descriptions-item>
        <el-descriptions-item v-if="detail.ticket.resolveNote" label="解决说明" :span="3">
          {{ detail.ticket.resolveNote }}
        </el-descriptions-item>
      </el-descriptions>

      <div class="actions">
        <template v-for="a in availableActions" :key="a.action">
          <el-button v-if="!a.needReason" size="small" type="primary" :loading="acting" @click="doAction(a)">{{ a.label }}</el-button>
          <el-popconfirm v-else title="确认执行该操作？" width="200" @confirm="doAction(a)">
            <template #reference>
              <el-button size="small" type="primary" :loading="acting">{{ a.label }}</el-button>
            </template>
          </el-popconfirm>
        </template>
      </div>

      <div class="attachments">
        <div class="att-head">
          <h4>附件</h4>
          <el-upload :show-file-list="false" :before-upload="beforeUpload" :http-request="doUpload">
            <el-button size="small" type="primary" plain :loading="uploading">上传附件</el-button>
          </el-upload>
        </div>
        <el-table v-if="attachments.length" :data="attachments" size="small" border>
          <el-table-column prop="originalName" label="文件名" min-width="200" show-overflow-tooltip />
          <el-table-column label="大小" width="100">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
          <el-table-column prop="createTime" label="上传时间" width="170" />
          <el-table-column label="操作" width="140">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="download(row)">下载</el-button>
              <el-popconfirm title="确认删除该附件？" width="180" @confirm="removeAtt(row)">
                <template #reference>
                  <el-button size="small" link type="danger">删除</el-button>
                </template>
              </el-popconfirm>
            </template>
          </el-table-column>
        </el-table>
        <div v-else class="muted">暂无附件</div>
      </div>

      <el-row :gutter="16">
        <el-col :span="14">
          <h4>流转时间线</h4>
          <el-timeline>
            <el-timeline-item v-for="f in detail.flows" :key="f.id" :timestamp="f.createTime">
              <b>{{ f.action }}</b>
              <span class="muted">（{{ f.fromStatus || '—' }} → {{ f.toStatus }}）</span>
              {{ f.operatorName ? '· ' + f.operatorName : '' }}
              <div v-if="f.comment" class="muted">{{ f.comment }}</div>
            </el-timeline-item>
          </el-timeline>
        </el-col>
        <el-col :span="10">
          <h4>沟通记录</h4>
          <div v-for="c in detail.comments" :key="c.id" class="comment">
            <b>{{ c.userName }}</b>
            <el-tag v-if="c.source === 'AI_ASSISTANT'" size="small" type="warning" class="mr8">AI</el-tag>
            <span class="muted">{{ c.createTime }}</span>
            <div>{{ c.content }}</div>
          </div>
          <div class="comment-input">
            <el-input v-model="comment" type="textarea" :rows="2" placeholder="添加评论…" />
            <el-button type="primary" size="small" class="mt8" @click="submitComment">发送</el-button>
          </div>
        </el-col>
      </el-row>
    </el-card>

    <!-- M5：AI 分析抽屉（RAG 流式 + 引用知识） -->
    <el-drawer v-model="aiVisible" title="AI 工单分析" size="720px" @closed="stopAi">
      <div class="ai-toolbar">
        <el-tag size="small">{{ ai.model || 'GLM' }}</el-tag>
        <el-tag size="small" type="info">检索 {{ ai.retrievalMs }}ms</el-tag>
        <el-tag v-if="ai.degraded" size="small" type="warning">知识库检索降级</el-tag>
        <el-tag v-if="ai.firstTokenMs" size="small" type="success">首 Token {{ ai.firstTokenMs }}ms</el-tag>
        <span class="ai-spacer" />
        <el-button v-if="aiLoading" size="small" @click="stopAi">停止</el-button>
        <el-button size="small" type="primary" plain :loading="aiLoading" @click="runAi">重新分析</el-button>
      </div>

      <el-alert v-if="ai.error" :title="ai.error" type="error" :closable="false" class="mt8" />

      <div v-if="aiRefs.length" class="ai-refs">
        <div class="ai-section-title">引用知识（{{ aiRefs.length }}）</div>
        <el-card v-for="(r, i) in aiRefs" :key="r.id || i" shadow="never" class="ai-ref">
          <div class="ai-ref-head">
            <span class="ai-ref-index">[K{{ i + 1 }}]</span>
            <span class="ai-ref-title">{{ r.title }}</span>
            <el-tag v-if="r.deviceType" size="small" type="info">{{ r.deviceType }}</el-tag>
            <span v-if="r.score != null" class="muted">score {{ Number(r.score).toFixed(3) }}</span>
          </div>
          <div class="ai-ref-summary">{{ r.summary || '—' }}</div>
        </el-card>
      </div>

      <el-collapse v-if="ai.reasoning" class="mt8">
        <el-collapse-item :title="`思考过程（${ai.reasoning.length} 字）`">
          <div class="ai-reasoning">{{ ai.reasoning }}</div>
        </el-collapse-item>
      </el-collapse>

      <div class="ai-section-title mt8">分析结论</div>
      <div class="ai-answer" ref="aiAnswerRef">
        <span v-if="!ai.answer && aiLoading" class="muted">正在检索知识并生成回答…</span>
        <span v-else-if="ai.answer" class="ai-answer-body" v-html="formatAnswer(ai.answer)" />
        <span v-else>点击“重新分析”生成</span>
        <span v-if="aiLoading" class="ai-cursor">▍</span>
      </div>

      <div v-if="ai.usage" class="ai-usage">
        <span>prompt {{ ai.usage.promptTokens }}</span>
        <span>completion {{ ai.usage.completionTokens }}</span>
        <span>total {{ ai.usage.totalTokens }}</span>
        <span>耗时 {{ ai.usage.latencyMs }}ms</span>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, reactive, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getTicket, ticketAction, addComment,
  listAttachments, uploadAttachment, downloadAttachment, deleteAttachment
} from '../api/ticket'
import { chatStream } from '../api/ai'

const route = useRoute()
const id = route.params.id
const detail = ref(null)
const acting = ref(false)
const comment = ref('')
const attachments = ref([])
const uploading = ref(false)

// ===== M5 AI 分析（SSE 流式）=====
const aiVisible = ref(false)
const aiLoading = ref(false)
const aiAnswerRef = ref(null)
const ai = reactive({
  model: '', retrievalMs: 0, degraded: false, firstTokenMs: 0,
  answer: '', reasoning: '', refs: [], usage: null, error: ''
})
const aiRefs = computed(() => ai.refs || [])
let aiAbort = null

function openAi() {
  aiVisible.value = true
  if (!ai.answer) runAi()
}

function stopAi() {
  if (aiAbort) {
    aiAbort.abort()
    aiAbort = null
  }
  aiLoading.value = false
}

/** 展示层轻量格式化：把模型返回的 Markdown 片段转成可读结构（先转义，防注入） */
function formatAnswer(text) {
  const esc = String(text)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
  return esc
    .replace(/^###\s+(.+)$/gm, '<div class="ai-h3">$1</div>')
    .replace(/^##\s+(.+)$/gm, '<div class="ai-h2">$1</div>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/^\s*\d+\.\s+(.+)$/gm, '<div class="ai-li">$1</div>')
    .replace(/^\s*[-*]\s+(.+)$/gm, '<div class="ai-li ai-li-dash">$1</div>')
}

async function scrollAiBottom() {
  await nextTick()
  const el = aiAnswerRef.value
  if (el) el.scrollTop = el.scrollHeight
}

async function runAi() {
  stopAi()
  Object.assign(ai, { answer: '', reasoning: '', refs: [], usage: null, error: '', degraded: false, retrievalMs: 0, firstTokenMs: 0 })
  aiLoading.value = true
  aiAbort = new AbortController()
  const question = `请分析该工单“${detail.value?.ticket?.title || ''}”的可能原因、排查步骤与处理建议；知识库有相关 SOP 请引用。`
  try {
    await chatStream({
      question,
      ticketId: String(id),
      topK: 5
    }, {
      meta: (m) => {
        ai.model = m.model
        ai.retrievalMs = m.retrievalMs
        ai.degraded = !!m.degraded
        ai.refs = m.refs || []
      },
      reasoning: (d) => { ai.reasoning += d.delta || '' },
      delta: (d) => { ai.answer += d.delta || ''; scrollAiBottom() },
      usage: (u) => {
        ai.usage = u
        ai.firstTokenMs = u.firstTokenMs
      },
      error: (e) => { ai.error = e.message || 'AI 服务异常' },
      done: () => {}
    }, aiAbort.signal)
  } catch (e) {
    if (e.name !== 'AbortError') {
      ai.error = e.message || 'AI 分析失败'
      ElMessage.error(ai.error)
    }
  } finally {
    aiLoading.value = false
    aiAbort = null
  }
}


const ALLOWED_EXT = ['jpg', 'jpeg', 'png', 'gif', 'bmp', 'webp', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'zip', 'log', 'txt']
const MAX_SIZE = 20 * 1024 * 1024

function fmtSize(n) {
  if (n == null) return '-'
  if (n < 1024) return n + ' B'
  if (n < 1024 * 1024) return (n / 1024).toFixed(1) + ' KB'
  return (n / 1024 / 1024).toFixed(1) + ' MB'
}

/** 前端先校验（后端为准）：20MB + 白名单 */
function beforeUpload(file) {
  if (file.size > MAX_SIZE) {
    ElMessage.error('文件超过 20MB 上限')
    return false
  }
  const ext = (file.name.split('.').pop() || '').toLowerCase()
  if (!ALLOWED_EXT.includes(ext)) {
    ElMessage.error('不支持的文件类型：' + ext)
    return false
  }
  return true
}

async function doUpload({ file }) {
  uploading.value = true
  try {
    await uploadAttachment(id, file)
    ElMessage.success('上传成功')
    await loadAttachments()
  } catch (e) {
    ElMessage.error(e.message || '上传失败')
  } finally {
    uploading.value = false
  }
}

async function download(row) {
  try {
    const blob = await downloadAttachment(id, row.id)
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = row.originalName
    a.click()
    URL.revokeObjectURL(url)
  } catch (e) {
    ElMessage.error(e.message || '下载失败')
  }
}

async function removeAtt(row) {
  try {
    await deleteAttachment(id, row.id)
    ElMessage.success('已删除')
    await loadAttachments()
  } catch (e) {
    ElMessage.error(e.message || '删除失败')
  }
}

async function loadAttachments() {
  try {
    attachments.value = await listAttachments(id) || []
  } catch { attachments.value = [] }
}

const statusMap = {
  DRAFT: '草稿', SUBMITTED: '待受理', ACCEPTED: '已受理', PROCESSING: '处理中',
  SUSPENDED: '挂起', RESOLVED: '待验证', CLOSED: '已关闭', TERMINATED: '已终止'
}
function statusType(s) {
  return { SUBMITTED: 'warning', PROCESSING: 'primary', SUSPENDED: 'info', RESOLVED: 'success',
    CLOSED: 'success', TERMINATED: 'danger', DRAFT: 'info' }[s] || 'info'
}

/** 按状态显隐操作（挂起/终止/解决走原因输入，resolve 还需说明） */
const availableActions = computed(() => {
  const s = detail.value?.ticket?.status
  const list = []
  if (s === 'SUBMITTED') list.push({ action: 'accept', label: '受理' })
  if (s === 'ACCEPTED') list.push({ action: 'start', label: '开工' })
  if (s === 'PROCESSING') {
    list.push({ action: 'suspend', label: '挂起', needReason: true },
      { action: 'resolve', label: '提交验证', needReason: true })
  }
  if (s === 'SUSPENDED') list.push({ action: 'resume', label: '恢复' })
  if (s === 'RESOLVED') list.push({ action: 'confirm', label: '确认关闭' },
    { action: 'reject', label: '驳回' })
  return list
})

const reasonActions = { suspend: '请输入挂起原因', resolve: '请输入解决说明' }

async function doAction(a) {
  let data
  if (a.action === 'suspend' || a.action === 'resolve') {
    try {
      const { value } = await ElMessageBox.prompt(reasonActions[a.action], a.label, {
        inputValidator: (v) => (v && v.trim()) || '内容不能为空'
      })
      data = a.action === 'resolve' ? { resolveNote: value } : { reason: value }
    } catch { return }
  }
  acting.value = true
  try {
    await ticketAction(id, a.action, data)
    ElMessage.success('操作成功')
    await load()
  } catch (e) {
    ElMessage.error(e.message || '操作失败')
  } finally {
    acting.value = false
  }
}

async function submitComment() {
  if (!comment.value.trim()) return
  await addComment(id, comment.value.trim())
  comment.value = ''
  await load()
}

async function load() {
  detail.value = await getTicket(id)
  await loadAttachments()
}

onMounted(load)
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; gap: 12px; }
.head > span { font-size: 17px; font-weight: 600; letter-spacing: .02em; }
.actions { margin: 18px 0; display: flex; gap: 8px; flex-wrap: wrap; }
.muted { color: var(--muted); font-size: 12px; }
.mono { font-family: var(--font-mono); font-size: 12px; letter-spacing: -.01em; }
.comment { border-top: 1px dashed var(--line); padding: 10px 0; }
.comment-input { margin-top: 12px; }
.mt8 { margin-top: 8px; }
.mr8 { margin-right: 8px; }
.attachments { margin: 8px 0 18px; }
.att-head { display: flex; justify-content: space-between; align-items: center; }
.att-head h4 { margin-bottom: 6px; }
.attachments h4,
:deep(.el-row) h4 { margin: 4px 0 10px; font-size: 13px; letter-spacing: .1em; color: var(--muted); }

/* M5 AI 分析 */
.ai-toolbar { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ai-spacer { flex: 1; }
.ai-section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-weight: 600;
  font-size: 12px;
  letter-spacing: .12em;
  color: var(--muted);
  margin-bottom: 10px;
}
.ai-section-title::before {
  content: "";
  width: 14px;
  height: 2px;
  background: var(--amber);
}
.ai-refs { margin-top: 16px; }
.ai-ref {
  margin-bottom: 10px;
  background: var(--surface-2);
  border: 1px solid var(--line);
  border-left: 3px solid var(--amber);
}
.ai-ref :deep(.el-card__body) { padding: 12px 14px; }
.ai-ref-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.ai-ref-index { color: var(--amber); font-family: var(--font-mono); font-weight: 600; font-size: 11.5px; }
.ai-ref-title { font-weight: 600; font-size: 13px; }
.ai-ref-summary { color: var(--ink-2); font-size: 12px; margin-top: 6px; line-height: 1.7; }
.ai-reasoning { white-space: pre-wrap; font-size: 12px; color: var(--muted); line-height: 1.75; max-height: 260px; overflow: auto; }
.ai-answer {
  white-space: pre-wrap; line-height: 1.85; font-size: 13.5px; color: var(--ink);
  background:
    linear-gradient(180deg, rgba(180, 90, 30, .035), transparent 120px),
    var(--surface);
  border: 1px solid var(--line); border-radius: 8px;
  padding: 16px 18px; min-height: 120px; max-height: 46vh; overflow: auto;
  box-shadow: 0 1px 0 rgba(28, 35, 42, .03) inset;
}
.ai-cursor { color: var(--amber); animation: blink 1s infinite; }
.ai-answer :deep(.ai-h2),
.ai-answer :deep(.ai-h3) {
  margin: 14px 0 6px;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: .06em;
  color: var(--ink);
}
.ai-answer :deep(.ai-h3)::before {
  content: "";
  display: inline-block;
  width: 3px;
  height: 11px;
  margin-right: 8px;
  vertical-align: 1px;
  background: var(--amber);
}
.ai-answer :deep(.ai-h3:first-child),
.ai-answer :deep(.ai-h2:first-child) { margin-top: 0; }
.ai-answer :deep(.ai-li) { padding-left: 12px; position: relative; }
.ai-answer :deep(.ai-li)::before {
  content: "·";
  position: absolute;
  left: 2px;
  color: var(--amber);
  font-weight: 700;
}
.ai-answer :deep(strong) { color: var(--ink); font-weight: 700; }
@keyframes blink { 50% { opacity: 0; } }
.ai-usage {
  margin-top: 14px; display: flex; gap: 16px; flex-wrap: wrap;
  font-family: var(--font-mono); font-size: 11px; letter-spacing: .02em;
  color: var(--muted); border-top: 1px dashed var(--line); padding-top: 10px;
}

@media (max-width: 760px) {
  .head { flex-direction: column; align-items: flex-start; }
  :deep(.el-row) .el-col { max-width: 100%; flex: 0 0 100%; }
}
</style>
