<template>
  <div class="observe">
    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <div>
            <div class="card-title">调用观测</div>
            <div class="card-sub">数据来自 ai_call_log 实测：调用量 / 耗时 / 费用 / 失败与护栏拦截 / 工具链 / prompt 版本</div>
          </div>
          <el-button size="small" :loading="loading" @click="reload">刷新</el-button>
        </div>
      </template>

      <div class="filters">
        <el-date-picker v-model="range" type="daterange" unlink-panels value-format="YYYY-MM-DD"
                        start-placeholder="开始日期" end-placeholder="结束日期" size="small" style="width: 240px" />
        <el-input v-model="filters.userId" size="small" placeholder="用户 ID" clearable style="width: 120px" />
        <el-select v-model="filters.scene" size="small" placeholder="全部场景" clearable style="width: 140px">
          <el-option v-for="s in scenes" :key="s" :label="s" :value="s" />
        </el-select>
        <el-input v-model="filters.model" size="small" placeholder="模型名" clearable style="width: 150px" />
        <el-select v-model="filters.status" size="small" placeholder="全部状态" clearable style="width: 130px">
          <el-option v-for="s in statuses" :key="s" :label="s" :value="s" />
        </el-select>
        <el-button size="small" type="primary" :loading="loading" @click="reload">查询</el-button>
        <el-button size="small" @click="resetFilters">重置</el-button>
      </div>

      <div v-if="overview" class="kpis">
        <div class="kpi"><b>{{ fmtNum(overview.calls) }}</b><span>调用次数</span></div>
        <div class="kpi"><b>{{ fmtNum(overview.totalTokens) }}</b><span>总 tokens</span></div>
        <div class="kpi"><b>¥{{ fmtMoney(overview.estimatedCostCny) }}</b><span>估算费用</span></div>
        <div class="kpi"><b>{{ overview.latency?.p50Ms ?? 0 }}ms</b><span>P50 耗时</span></div>
        <div class="kpi"><b>{{ overview.latency?.p95Ms ?? 0 }}ms</b><span>P95 耗时</span></div>
        <div class="kpi danger"><b>{{ overview.errorCalls ?? 0 }}</b><span>失败</span></div>
        <div class="kpi warn"><b>{{ overview.blockedCalls ?? 0 }}</b><span>护栏拦截</span></div>
        <div class="kpi ok"><b>{{ overview.cacheHitCalls ?? 0 }}</b><span>缓存命中</span></div>
      </div>

      <div v-if="overview" class="grid">
        <div class="panel">
          <div class="panel-title">调用量趋势（tokens）</div>
          <div v-if="overview.trend?.length" class="bars">
            <div v-for="d in overview.trend" :key="d.day" class="bar-col" :title="`${d.day} 调用 ${d.calls} 次 / ${fmtNum(d.tokens)} tokens`">
              <div class="bar-val">{{ fmtNum(d.tokens) }}</div>
              <div class="bar" :style="{ height: barH(d.tokens) }" />
              <div class="bar-day">{{ String(d.day).slice(5) }}</div>
            </div>
          </div>
          <el-empty v-else :image-size="56" description="所选范围暂无调用" />
        </div>

        <div class="panel">
          <div class="panel-title">耗时分布（P50 {{ overview.latency?.p50Ms ?? 0 }}ms / P95 {{ overview.latency?.p95Ms ?? 0 }}ms）</div>
          <div v-for="b in overview.latency?.buckets || []" :key="b.bucket" class="lat-row">
            <span class="lat-label">{{ b.bucket }}</span>
            <div class="lat-track"><div class="lat-fill" :style="{ width: pct(b.calls) }" /></div>
            <span class="lat-val">{{ b.calls }}</span>
          </div>
          <div class="panel-note">样本 {{ overview.latency?.sampleSize ?? 0 }} 条（不含工具调用行），平均值 {{ overview.latency?.avgMs ?? 0 }}ms，最大 {{ overview.latency?.maxMs ?? 0 }}ms</div>
        </div>
      </div>

      <div v-if="overview" class="grid three">
        <div class="panel">
          <div class="panel-title">按模型</div>
          <div v-for="m in overview.byModel || []" :key="m.model" class="split-row">
            <span class="mono">{{ m.model || '—' }}</span>
            <b>{{ fmtNum(m.tokens) }} <i class="cost">¥{{ fmtMoney(m.estimatedCostCny) }}</i></b>
          </div>
          <el-empty v-if="!(overview.byModel || []).length" :image-size="48" description="无数据" />
        </div>
        <div class="panel">
          <div class="panel-title">按场景</div>
          <div v-for="s in overview.byScene || []" :key="s.scene" class="split-row">
            <span>{{ s.scene }}</span><b>{{ s.calls }} 次 / {{ fmtNum(s.tokens) }}</b>
          </div>
        </div>
        <div class="panel">
          <div class="panel-title">按用户（Top 10）</div>
          <div v-for="u in overview.byUser || []" :key="u.userId" class="split-row">
            <span>用户 {{ u.userId }}</span><b>{{ u.calls }} 次 / {{ fmtNum(u.tokens) }}</b>
          </div>
          <el-empty v-if="!(overview.byUser || []).length" :image-size="48" description="无用户维度数据" />
        </div>
      </div>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <span class="card-title">调用列表</span>
          <span class="card-sub">点击行查看单条详情（含同 traceId 工具链与 prompt 版本内容）</span>
        </div>
      </template>

      <el-table :data="calls.items" size="small" border height="360" @row-click="openDetail">
        <el-table-column label="时间" width="160">
          <template #default="{ row }">{{ fmtTime(row.createTime) }}</template>
        </el-table-column>
        <el-table-column label="trace" width="120">
          <template #default="{ row }"><span class="mono">{{ shortTrace(row.traceId) }}</span></template>
        </el-table-column>
        <el-table-column label="场景" width="110">
          <template #default="{ row }"><el-tag size="small" :type="sceneType(row.scene)">{{ row.scene }}</el-tag></template>
        </el-table-column>
        <el-table-column label="模型 / 工具" min-width="170">
          <template #default="{ row }">
            <div>{{ row.model || '—' }}</div>
            <div v-if="row.toolName" class="mono sub">{{ row.toolName }}({{ row.toolArgs }})</div>
          </template>
        </el-table-column>
        <el-table-column label="tokens" width="90">
          <template #default="{ row }">{{ fmtNum(row.totalTokens) }}</template>
        </el-table-column>
        <el-table-column label="耗时" width="90">
          <template #default="{ row }">{{ row.latencyMs == null ? '—' : row.latencyMs + 'ms' }}</template>
        </el-table-column>
        <el-table-column label="费用" width="90">
          <template #default="{ row }">¥{{ fmtMoney(row.estimatedCostCny) }}</template>
        </el-table-column>
        <el-table-column label="状态" width="130">
          <template #default="{ row }">
            <el-tag size="small" :type="statusType(row.status)">{{ row.status }}</el-tag>
            <el-tag v-if="row.guardBlocked" size="small" type="danger" effect="plain" class="ml4">拦截</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="prompt" width="110">
          <template #default="{ row }"><span class="mono">{{ row.promptVersion || '—' }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="80" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click.stop="openDetail(row)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <div class="pager">
        <el-pagination v-model:current-page="page" v-model:page-size="size" :total="calls.total"
                       :page-sizes="[20, 50, 100]" layout="total, sizes, prev, pager, next"
                       size="small" @current-change="loadCalls" @size-change="onSizeChange" />
      </div>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <span class="card-title">Prompt 版本</span>
          <div class="head-actions">
            <el-select v-model="promptScene" size="small" style="width: 150px" @change="loadPrompts">
              <el-option label="CHAT（RAG 问答）" value="CHAT" />
              <el-option label="ASSISTANT（工单助手）" value="ASSISTANT" />
            </el-select>
            <el-button v-if="isAdmin" size="small" type="primary" @click="openPromptDialog">新增版本</el-button>
          </div>
        </div>
      </template>

      <el-table :data="prompts" size="small" border>
        <el-table-column prop="version" label="版本" width="150" />
        <el-table-column prop="scene" label="场景" width="120" />
        <el-table-column label="状态" width="100">
          <template #default="{ row }">
            <el-tag size="small" :type="row.active ? 'success' : 'info'">{{ row.active ? '生效中' : '历史' }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.createTime) }}</template>
        </el-table-column>
        <el-table-column label="内容预览" min-width="260">
          <template #default="{ row }"><span class="preview">{{ oneLine(row.content) }}</span></template>
        </el-table-column>
        <el-table-column label="操作" width="90">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="viewPrompt(row)">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-drawer v-model="detailVisible" size="620px" title="调用详情">
      <div v-if="detail">
        <el-descriptions :column="2" size="small" border>
          <el-descriptions-item label="记录 ID">{{ detail.call.id }}</el-descriptions-item>
          <el-descriptions-item label="traceId">{{ detail.call.traceId || '—' }}</el-descriptions-item>
          <el-descriptions-item label="场景">{{ detail.call.scene }}</el-descriptions-item>
          <el-descriptions-item label="模型">{{ detail.call.model || '—' }}</el-descriptions-item>
          <el-descriptions-item label="用户">{{ detail.call.userId ?? '—' }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ fmtTime(detail.call.createTime) }}</el-descriptions-item>
          <el-descriptions-item label="tokens">
            {{ detail.call.promptTokens }} / {{ detail.call.completionTokens }}（总 {{ detail.call.totalTokens }}）
          </el-descriptions-item>
          <el-descriptions-item label="估算费用">¥{{ fmtMoney(detail.estimatedCostCny) }}</el-descriptions-item>
          <el-descriptions-item label="耗时">{{ detail.call.latencyMs ?? '—' }}ms</el-descriptions-item>
          <el-descriptions-item label="首 token">{{ detail.call.firstTokenMs ?? '—' }}ms</el-descriptions-item>
          <el-descriptions-item label="状态">{{ detail.call.status }}</el-descriptions-item>
          <el-descriptions-item label="降级 / 护栏">{{ detail.call.degraded ? '降级' : '正常' }} / {{ detail.call.guardBlocked ? '拦截' : '未拦截' }}</el-descriptions-item>
          <el-descriptions-item label="prompt 版本">{{ detail.call.promptVersion || '—' }}</el-descriptions-item>
          <el-descriptions-item label="错误">{{ detail.call.errorMsg || '—' }}</el-descriptions-item>
        </el-descriptions>

        <div class="drawer-title">工具调用链（同 traceId）</div>
        <el-table :data="detail.trace || []" size="small" border>
          <el-table-column prop="scene" label="场景" width="110" />
          <el-table-column prop="toolName" label="工具" width="150" />
          <el-table-column prop="toolArgs" label="入参" min-width="160" show-overflow-tooltip />
          <el-table-column prop="latencyMs" label="耗时" width="90" />
          <el-table-column prop="status" label="状态" width="100" />
        </el-table>

        <div class="drawer-title">当次使用的 prompt（{{ detail.prompt?.scene }} / {{ detail.prompt?.version || '—' }}）</div>
        <div v-if="detail.prompt?.found" class="prompt-box">{{ detail.prompt.content }}</div>
        <el-alert v-else type="info" :closable="false" :title="detail.prompt?.note || '未记录 prompt 版本'" />
      </div>
    </el-drawer>

    <el-dialog v-model="promptVisible" title="新增 prompt 版本（立即生效）" width="680px">
      <el-form label-width="80px">
        <el-form-item label="场景">
          <el-select v-model="promptForm.scene" style="width: 220px">
            <el-option label="CHAT" value="CHAT" />
            <el-option label="ASSISTANT" value="ASSISTANT" />
          </el-select>
        </el-form-item>
        <el-form-item label="版本号">
          <el-input v-model="promptForm.version" placeholder="留空自动生成，如 chat-v2" />
        </el-form-item>
        <el-form-item label="内容">
          <el-input v-model="promptForm.content" type="textarea" :rows="12" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="promptVisible = false">取消</el-button>
        <el-button type="primary" :loading="savingPrompt" @click="savePrompt">保存并生效</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="promptViewVisible" :title="`prompt 内容 · ${viewPromptRow?.version || ''}`" width="680px">
      <pre class="prompt-pre">{{ viewPromptRow?.content }}</pre>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import {
  archivePrompt, observeCallDetail, observeCalls, observeOverview, observePrompts
} from '../api/observe'

const auth = useAuthStore()
const isAdmin = computed(() => (auth.user?.roles || []).includes('ADMIN'))

const scenes = ['CHAT_STREAM', 'CHAT_SYNC', 'AGENT', 'AGENT_TOOL']
const statuses = ['SUCCESS', 'ERROR', 'DEGRADED', 'BLOCKED', 'CACHE_HIT']

const today = new Date()
const weekAgo = new Date(today.getTime() - 6 * 86400000)
const range = ref([fmtDate(weekAgo), fmtDate(today)])
const filters = reactive({ userId: '', scene: '', model: '', status: '' })

const overview = ref(null)
const calls = ref({ items: [], total: 0 })
const page = ref(1)
const size = ref(20)
const loading = ref(false)

const detailVisible = ref(false)
const detail = ref(null)

const prompts = ref([])
const promptScene = ref('CHAT')
const promptVisible = ref(false)
const promptViewVisible = ref(false)
const viewPromptRow = ref(null)
const savingPrompt = ref(false)
const promptForm = reactive({ scene: 'CHAT', version: '', content: '' })

function fmtDate(d) {
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${m}-${day}`
}

function params() {
  return {
    from: range.value?.[0],
    to: range.value?.[1],
    userId: filters.userId || undefined,
    scene: filters.scene || undefined,
    model: filters.model || undefined,
    status: filters.status || undefined
  }
}

async function loadOverview() {
  overview.value = await observeOverview(params())
}

async function loadCalls() {
  calls.value = await observeCalls({ ...params(), page: page.value, size: size.value })
}

async function reload() {
  loading.value = true
  try {
    await Promise.all([loadOverview(), loadCalls()])
  } catch (e) {
    ElMessage.error(e.message || '查询失败')
  } finally {
    loading.value = false
  }
}

function resetFilters() {
  range.value = [fmtDate(weekAgo), fmtDate(today)]
  filters.userId = ''
  filters.scene = ''
  filters.model = ''
  filters.status = ''
  page.value = 1
  reload()
}

function onSizeChange() {
  page.value = 1
  loadCalls()
}

async function loadPrompts() {
  try {
    prompts.value = await observePrompts(promptScene.value)
  } catch (e) {
    ElMessage.error(e.message || '读取 prompt 版本失败')
  }
}

async function openDetail(row) {
  try {
    detail.value = await observeCallDetail(row.id)
    detailVisible.value = true
  } catch (e) {
    ElMessage.error(e.message || '读取详情失败')
  }
}

function openPromptDialog() {
  promptForm.scene = promptScene.value
  promptForm.version = ''
  promptForm.content = ''
  promptVisible.value = true
}

async function savePrompt() {
  if (!promptForm.content.trim()) {
    ElMessage.warning('prompt 内容不能为空')
    return
  }
  savingPrompt.value = true
  try {
    await archivePrompt({ ...promptForm })
    ElMessage.success('新版本已生效')
    promptVisible.value = false
    promptScene.value = promptForm.scene
    await loadPrompts()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    savingPrompt.value = false
  }
}

function viewPrompt(row) {
  viewPromptRow.value = row
  promptViewVisible.value = true
}

function fmtNum(v) {
  const n = Number(v || 0)
  return n.toLocaleString('zh-CN')
}

function fmtMoney(v) {
  const n = Number(v || 0)
  return n.toFixed(4)
}

function fmtTime(t) {
  if (!t) return '—'
  return String(t).replace('T', ' ').replace(/\.\d+$/, '')
}

function shortTrace(t) {
  if (!t) return '—'
  return t.length > 12 ? `${t.slice(0, 6)}…${t.slice(-4)}` : t
}

function oneLine(s) {
  return (s || '').replace(/\s+/g, ' ').slice(0, 90)
}

function barH(v) {
  const list = overview.value?.trend || []
  const max = Math.max(1, ...list.map((d) => Number(d.tokens || 0)))
  return `${Math.max(4, Math.round((Number(v || 0) / max) * 88))}px`
}

function pct(v) {
  const list = overview.value?.latency?.buckets || []
  const max = Math.max(1, ...list.map((b) => Number(b.calls || 0)))
  return `${Math.round((Number(v || 0) / max) * 100)}%`
}

function sceneType(scene) {
  if (scene === 'AGENT_TOOL') return 'warning'
  if (scene === 'AGENT') return 'success'
  return 'primary'
}

function statusType(status) {
  if (status === 'SUCCESS') return 'success'
  if (status === 'ERROR' || status === 'BLOCKED') return 'danger'
  if (status === 'DEGRADED') return 'warning'
  return 'info'
}

onMounted(() => {
  reload()
  loadPrompts()
})
</script>

<style scoped>
.observe { display: flex; flex-direction: column; gap: 14px; }
.block { border: 1px solid var(--line); }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.head-actions { display: flex; align-items: center; gap: 8px; }
.card-title { font-weight: 700; font-size: 15px; letter-spacing: .04em; }
.card-sub { margin-top: 3px; color: var(--muted); font-size: 12px; }
.filters { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-bottom: 14px; }
.kpis { display: grid; grid-template-columns: repeat(8, minmax(0, 1fr)); gap: 10px; margin-bottom: 14px; }
.kpi {
  padding: 12px 14px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-2);
  display: flex; flex-direction: column; gap: 4px;
}
.kpi b { font-family: var(--font-mono); font-size: 18px; color: var(--ink); }
.kpi span { color: var(--muted); font-size: 11.5px; }
.kpi.danger b { color: var(--rust); }
.kpi.warn b { color: var(--amber); }
.kpi.ok b { color: var(--teal); }
.grid { display: grid; grid-template-columns: 1.4fr 1fr; gap: 14px; margin-bottom: 14px; }
.grid.three { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.panel { border: 1px solid var(--line); border-radius: 8px; padding: 14px; background: var(--surface); }
.panel-title { font-weight: 600; font-size: 13px; margin-bottom: 10px; }
.panel-note { margin-top: 10px; color: var(--muted); font-size: 11.5px; line-height: 1.6; }
.bars { display: flex; align-items: flex-end; gap: 10px; height: 128px; padding-top: 6px; }
.bar-col { flex: 1; display: flex; flex-direction: column; align-items: center; justify-content: flex-end; height: 100%; }
.bar-val { font-family: var(--font-mono); font-size: 10px; color: var(--muted); margin-bottom: 4px; }
.bar { width: 60%; min-width: 12px; border-radius: 3px 3px 0 0; background: linear-gradient(180deg, var(--amber), rgba(180, 90, 30, .35)); }
.bar-day { margin-top: 6px; font-family: var(--font-mono); font-size: 10.5px; color: var(--muted); }
.lat-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
.lat-label { width: 78px; font-size: 11.5px; color: var(--ink-2); }
.lat-track { flex: 1; height: 10px; border-radius: 999px; background: var(--surface-2); overflow: hidden; }
.lat-fill { height: 100%; border-radius: 999px; background: linear-gradient(90deg, var(--teal), rgba(47, 125, 102, .35)); }
.lat-val { width: 40px; text-align: right; font-family: var(--font-mono); font-size: 11px; color: var(--muted); }
.split-row { display: flex; justify-content: space-between; gap: 10px; padding: 6px 0; border-bottom: 1px dashed var(--line); font-size: 12.5px; }
.split-row:last-child { border-bottom: 0; }
.split-row b { font-family: var(--font-mono); font-size: 12px; }
.split-row .cost { color: var(--amber); font-style: normal; margin-left: 6px; }
.mono { font-family: var(--font-mono); }
.sub { color: var(--muted); font-size: 11px; }
.preview { color: var(--ink-2); font-size: 12px; }
.ml4 { margin-left: 4px; }
.pager { display: flex; justify-content: flex-end; margin-top: 10px; }
.drawer-title { margin: 18px 0 8px; font-weight: 700; font-size: 13px; }
.prompt-box {
  white-space: pre-wrap; font-family: var(--font-mono); font-size: 12px; line-height: 1.7;
  padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-2);
  max-height: 320px; overflow: auto;
}
.prompt-pre { white-space: pre-wrap; font-family: var(--font-mono); font-size: 12px; line-height: 1.7; margin: 0; }
@media (max-width: 1100px) {
  .kpis { grid-template-columns: repeat(4, minmax(0, 1fr)); }
  .grid, .grid.three { grid-template-columns: 1fr; }
}
</style>
