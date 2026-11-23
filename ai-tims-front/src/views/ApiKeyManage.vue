<template>
  <div class="keys">
    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <div>
            <div class="card-title">余额与额度</div>
            <div class="card-sub">智谱未开放余额查询接口，这里展示本地累计消耗与管理员额度之差，明确标注为估算值</div>
          </div>
          <el-tag type="warning" effect="dark" size="small">本地估算 · 非官方余量</el-tag>
        </div>
      </template>

      <div v-if="balance" class="balance">
        <div class="balance-main">
          <div class="balance-num">¥{{ fmtMoney(balance.remainingCny) }}</div>
          <div class="balance-label">估算剩余（额度 − 本地累计消耗）</div>
          <el-progress :percentage="Number(balance.usedPercent) || 0" :stroke-width="10" :show-text="false" />
          <div class="balance-meta">
            <span>已消耗 <b>¥{{ fmtMoney(balance.estimatedCostCny) }}</b></span>
            <span>额度 <b>¥{{ fmtMoney(balance.quotaCny) }}</b></span>
            <span>已用 {{ balance.usedPercent ?? 0 }}%</span>
          </div>
        </div>
        <div class="balance-side">
          <div class="side-row"><span>数据来源</span><b>{{ balance.source }}</b></div>
          <div class="side-row"><span>官方接口</span><b>{{ balance.officialAvailable ? '可用' : '不可用' }}</b></div>
          <div class="side-row"><span>查询时间</span><b class="mono">{{ fmtTime(balance.checkedAt) }}</b></div>
          <div class="probe-title">接口探测</div>
          <div v-for="p in balance.probe || []" :key="p.path" class="probe-row">
            <span class="mono">{{ p.path }}</span><el-tag size="small" type="info">{{ p.result }}</el-tag>
          </div>
          <div class="side-note">{{ balance.note }}</div>
        </div>
      </div>

      <div class="quota-edit">
        <span>管理员填写额度（元）</span>
        <el-input-number v-model="quotaInput" :min="0" :precision="2" :step="10" size="small" style="width: 160px" />
        <el-button size="small" type="primary" :loading="savingQuota" @click="saveQuota">保存额度</el-button>
        <span class="quota-note">额度只用于本地估算，不会同步到智谱控制台</span>
      </div>
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <div>
            <div class="card-title">模型 API Key</div>
            <div class="card-sub">按租户隔离，AES-256-GCM 加密存储；列表只显示尾号，改完立即生效，无需重启</div>
          </div>
          <el-button size="small" type="primary" @click="openEdit(null)">新增 Key</el-button>
        </div>
      </template>

      <el-table :data="keys" size="small" border>
        <el-table-column prop="provider" label="供应商" width="110" />
        <el-table-column prop="model" label="模型" min-width="170" />
        <el-table-column label="Key" width="150">
          <template #default="{ row }"><span class="mono">{{ row.masked }}</span></template>
        </el-table-column>
        <el-table-column label="更新人" width="120">
          <template #default="{ row }">{{ row.updatedBy ?? '—' }}</template>
        </el-table-column>
        <el-table-column label="更新时间" width="180">
          <template #default="{ row }">{{ fmtTime(row.updateTime) }}</template>
        </el-table-column>
        <el-table-column label="操作" width="200" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="openEdit(row)">更新</el-button>
            <el-button size="small" link type="warning" @click="onReveal(row)">查看</el-button>
            <el-popconfirm title="删除后该租户回落到默认 Key，确认？" width="250" @confirm="onDelete(row)">
              <template #reference><el-button size="small" link type="danger">删除</el-button></template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
      <el-alert v-if="fallbackNote" type="info" :closable="false" :title="fallbackNote" class="mt10" />
    </el-card>

    <el-card shadow="never" class="block">
      <template #header>
        <div class="card-head">
          <span class="card-title">操作审计</span>
          <span class="card-sub">新增 / 更新 / 删除 / 查看明文 / 额度调整全部留痕，不记录明文</span>
        </div>
      </template>
      <el-table :data="audits" size="small" border height="320">
        <el-table-column label="时间" width="170">
          <template #default="{ row }">{{ fmtTime(row.createTime) }}</template>
        </el-table-column>
        <el-table-column label="动作" width="110">
          <template #default="{ row }">
            <el-tag size="small" :type="auditType(row.action)">{{ row.action }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="provider" label="供应商" width="100" />
        <el-table-column prop="model" label="模型" width="150" />
        <el-table-column label="Key 尾号" width="110">
          <template #default="{ row }">{{ row.keyTail ? '****' + row.keyTail : '—' }}</template>
        </el-table-column>
        <el-table-column prop="operatorId" label="操作人" width="110" />
        <el-table-column prop="detail" label="说明" min-width="200" />
      </el-table>
    </el-card>

    <el-dialog v-model="editVisible" :title="editRow ? '更新 API Key' : '新增 API Key'" width="520px">
      <el-form label-width="90px">
        <el-form-item label="供应商">
          <el-select v-model="form.provider" style="width: 200px">
            <el-option label="智谱 zhipu" value="zhipu" />
          </el-select>
        </el-form-item>
        <el-form-item label="模型名">
          <el-input v-model="form.model" placeholder="如 glm-5.3-flash" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input v-model="form.apiKey" type="password" show-password
                    :placeholder="editRow ? '留空不修改，重新输入则覆盖' : '粘贴智谱 API Key'" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveKey">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="revealVisible" title="查看明文（已写入审计）" width="560px">
      <div v-if="revealRow" class="reveal">
        <div class="mono reveal-key">{{ revealRow.apiKey }}</div>
        <div class="reveal-meta">
          <span>尾号 ****{{ revealRow.keyTail }}</span>
          <span>查询时间 {{ fmtTime(revealRow.queryTime) }}</span>
          <el-button size="small" @click="copyKey">复制</el-button>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  deleteApiKey, getQuota, keyAudits, keyBalance, listApiKeys, revealApiKey, saveApiKey, setQuota as putQuota
} from '../api/observe'

const keys = ref([])
const audits = ref([])
const balance = ref(null)
const defaultModel = ref('glm-5.3-flash')
const fallbackNote = ref('')
const quotaInput = ref(0)
const savingQuota = ref(false)

const editVisible = ref(false)
const editRow = ref(null)
const saving = ref(false)
const form = reactive({ provider: 'zhipu', model: '', apiKey: '' })

const revealVisible = ref(false)
const revealRow = ref(null)

async function loadAll() {
  try {
    const [k, b, a, q] = await Promise.all([listApiKeys(), keyBalance(), keyAudits(50), getQuota()])
    keys.value = k.keys || []
    defaultModel.value = k.defaultModel || defaultModel.value
    fallbackNote.value = k.fallbackNote || ''
    balance.value = b
    audits.value = a || []
    quotaInput.value = Number(q.quotaCny || 0)
  } catch (e) {
    ElMessage.error(e.message || '加载失败')
  }
}

function openEdit(row) {
  editRow.value = row
  form.provider = row?.provider || 'zhipu'
  form.model = row?.model || defaultModel.value
  form.apiKey = ''
  editVisible.value = true
}

async function saveKey() {
  if (!form.apiKey.trim()) {
    ElMessage.warning('请填写 API Key')
    return
  }
  saving.value = true
  try {
    await saveApiKey({ ...form })
    ElMessage.success('已保存并立即生效')
    editVisible.value = false
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function onDelete(row) {
  try {
    await deleteApiKey(row.id)
    ElMessage.success('已删除，该租户回落到默认 Key')
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || '删除失败')
  }
}

async function onReveal(row) {
  try {
    revealRow.value = await revealApiKey(row.id)
    revealVisible.value = true
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || '查看失败')
  }
}

function copyKey() {
  navigator.clipboard?.writeText(revealRow.value?.apiKey || '')
  ElMessage.success('已复制')
}

async function saveQuota() {
  savingQuota.value = true
  try {
    await putQuota(Number(quotaInput.value || 0))
    ElMessage.success('额度已保存')
    await loadAll()
  } catch (e) {
    ElMessage.error(e.message || '额度保存失败')
  } finally {
    savingQuota.value = false
  }
}

function fmtMoney(v) {
  return Number(v || 0).toFixed(4)
}

function fmtTime(t) {
  if (!t) return '—'
  return String(t).replace('T', ' ').replace(/\.\d+$/, '')
}

function auditType(action) {
  if (action === 'DELETE') return 'danger'
  if (action === 'VIEW') return 'warning'
  if (action === 'QUOTA') return 'info'
  return 'success'
}

onMounted(loadAll)
</script>

<style scoped>
.keys { display: flex; flex-direction: column; gap: 14px; }
.block { border: 1px solid var(--line); }
.card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
.card-title { font-weight: 700; font-size: 15px; letter-spacing: .04em; }
.card-sub { margin-top: 3px; color: var(--muted); font-size: 12px; }
.balance { display: grid; grid-template-columns: 1.3fr 1fr; gap: 18px; }
.balance-main { padding: 6px 4px; }
.balance-num { font-family: var(--font-mono); font-size: 30px; font-weight: 700; color: var(--ink); }
.balance-label { color: var(--muted); font-size: 12px; margin: 4px 0 12px; }
.balance-meta { display: flex; gap: 18px; margin-top: 10px; font-size: 12px; color: var(--ink-2); flex-wrap: wrap; }
.balance-side { border-left: 1px solid var(--line); padding-left: 18px; }
.side-row { display: flex; justify-content: space-between; gap: 10px; padding: 4px 0; font-size: 12px; color: var(--muted); }
.side-row b { color: var(--ink); font-size: 12px; }
.probe-title { margin-top: 10px; font-size: 12px; font-weight: 600; }
.probe-row { display: flex; justify-content: space-between; align-items: center; padding: 3px 0; font-size: 11.5px; color: var(--muted); }
.side-note { margin-top: 8px; font-size: 11.5px; color: var(--muted); line-height: 1.6; }
.quota-edit { display: flex; align-items: center; gap: 10px; margin-top: 16px; padding-top: 14px; border-top: 1px dashed var(--line); font-size: 12.5px; flex-wrap: wrap; }
.quota-note { color: var(--muted); font-size: 11.5px; }
.mono { font-family: var(--font-mono); }
.mt10 { margin-top: 10px; }
.reveal-key { padding: 12px; border: 1px solid var(--line); border-radius: 8px; background: var(--surface-2); word-break: break-all; font-size: 13px; }
.reveal-meta { display: flex; align-items: center; gap: 14px; margin-top: 10px; font-size: 12px; color: var(--muted); }
@media (max-width: 900px) {
  .balance { grid-template-columns: 1fr; }
  .balance-side { border-left: 0; padding-left: 0; border-top: 1px solid var(--line); padding-top: 12px; }
}
</style>
