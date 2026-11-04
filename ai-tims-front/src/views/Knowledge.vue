<template>
  <div>
    <!-- 检索测试面板 -->
    <el-card shadow="never" class="mb12">
      <template #header>
        <div class="card-head">
          <span>知识检索</span>
          <el-tag v-if="searchResult && searchResult.fallback" type="warning" size="small">
            Milvus 不可用，已降级关键词
          </el-tag>
        </div>
      </template>
      <div class="search-bar">
        <el-input v-model="searchForm.query" placeholder="输入故障现象/关键词，如：贴片机 抛料" clearable
                  style="flex: 1" @keyup.enter="doSearch" />
        <el-radio-group v-model="searchForm.mode">
          <el-radio-button value="HYBRID">混合</el-radio-button>
          <el-radio-button value="VECTOR">向量</el-radio-button>
          <el-radio-button value="KEYWORD">关键词</el-radio-button>
        </el-radio-group>
        <el-input-number v-model="searchForm.topK" :min="1" :max="20" style="width: 110px" />
        <el-button type="primary" :loading="searching" @click="doSearch">检索</el-button>
      </div>
      <el-table v-if="searchResult" :data="searchResult.items" stripe size="small" class="mt12">
        <el-table-column type="index" label="#" width="45" />
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="applyDeviceType" label="设备类型" width="110" />
        <el-table-column prop="summary" label="摘要" min-width="240" show-overflow-tooltip />
        <el-table-column label="标签" width="160">
          <template #default="{ row }">
            <el-tag v-for="t in parseTags(row.tags)" :key="t" size="small" class="mr4">{{ t }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="score" label="得分" width="90" />
        <el-table-column label="操作" width="70" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewRow = row">查看</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="输入检索词后点击检索，可切换三种模式对比返回" :image-size="60" />
    </el-card>

    <!-- M6 AI 抽取审核中心（系统仅给建议，必须人工确认才执行；仅 ADMIN/审核员可见） -->
    <el-card v-if="canReview" shadow="never" class="mb12">
      <template #header>
        <div class="card-head">
          <span>AI 抽取审核</span>
          <div>
            <el-tag size="small" type="warning" effect="plain" class="mr8">仅给建议，须人工确认</el-tag>
            <el-button size="small" @click="loadExtraction">刷新</el-button>
          </div>
        </div>
      </template>
      <div class="filters">
        <el-select v-model="extractQuery.status" placeholder="状态" clearable style="width: 150px"
                   @change="loadExtraction">
          <el-option v-for="(v, k) in extractStatusMap" :key="k" :label="v" :value="k" />
        </el-select>
      </div>
      <el-table :data="extractRecords" v-loading="extractLoading" stripe size="small">
        <el-table-column prop="title" label="抽取标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="sourceTicketNo" label="来源工单" width="150" show-overflow-tooltip />
        <el-table-column prop="deviceType" label="设备类型" width="100" />
        <el-table-column label="相似度 / 建议" min-width="240">
          <template #default="{ row }">
            <el-tag :type="suggestType(row.dedupAction)" size="small" class="mr4">
              {{ suggestMap[row.dedupAction] || row.dedupAction }}
            </el-tag>
            <span v-if="row.dedupScore != null" class="score">{{ Number(row.dedupScore).toFixed(4) }}</span>
            <span v-if="row.dedupTargetTitle" class="target">→ {{ row.dedupTargetTitle }}</span>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="95">
          <template #default="{ row }">
            <el-tag :type="extractStatusType(row.status)" size="small">
              {{ extractStatusMap[row.status] || row.status }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="createTime" label="抽取时间" width="165" />
        <el-table-column label="操作" width="250" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="openExtractView(row)">查看</el-button>
            <el-button v-if="pendingExtract(row)" link type="primary" @click="openExtractEdit(row)">补录</el-button>
            <template v-if="canReview && pendingExtract(row)">
              <el-button link type="success" @click="doApproveExtract(row)">通过</el-button>
              <el-button link type="warning" @click="openMerge(row)">合并</el-button>
              <el-button link type="danger" @click="doRejectExtract(row)">驳回</el-button>
            </template>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination class="pager" layout="total, prev, pager, next" :total="extractTotal"
                     :page-size="extractQuery.size" v-model:current-page="extractQuery.page"
                     @current-change="loadExtraction" />
    </el-card>

    <!-- 知识列表 -->
    <el-card shadow="never">
      <template #header>
        <div class="card-head">
          <span>知识管理</span>
          <el-button type="primary" size="small" @click="openEdit()">新建知识</el-button>
        </div>
      </template>
      <div class="filters">
        <el-select v-model="query.status" placeholder="状态" clearable style="width: 130px" @change="load">
          <el-option v-for="(v, k) in statusMap" :key="k" :label="v" :value="k" />
        </el-select>
        <el-select v-model="query.deviceType" placeholder="设备类型" clearable style="width: 130px" @change="load">
          <el-option v-for="d in deviceTypes" :key="d" :label="d" :value="d" />
        </el-select>
        <el-input v-model="query.keyword" placeholder="标题/正文" clearable style="width: 180px"
                  @keyup.enter="load" />
        <el-button @click="load">查询</el-button>
      </div>
      <el-table :data="records" v-loading="loading" stripe>
        <el-table-column prop="title" label="标题" min-width="220" show-overflow-tooltip />
        <el-table-column prop="applyDeviceType" label="设备类型" width="110" />
        <el-table-column prop="categoryName" label="分类" width="100">
          <template #default="{ row }">{{ categoryName(row.categoryId) }}</template>
        </el-table-column>
        <el-table-column label="标签" width="180">
          <template #default="{ row }">
            <el-tag v-for="t in parseTags(row.tags).slice(0, 3)" :key="t" size="small" class="mr4">{{ t }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusMap[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="version" label="版本" width="65" />
        <el-table-column prop="vectorSyncedAt" label="向量同步时间" width="165" />
        <el-table-column prop="updateTime" label="更新时间" width="165" />
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="viewRow = row">查看</el-button>
            <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
            <el-button v-if="row.status === 'DRAFT' || row.status === 'REJECTED'"
                       link type="warning" @click="doSubmit(row)">提交</el-button>
            <template v-if="canReview">
              <el-button v-if="row.status === 'PENDING'" link type="success" @click="doPublish(row)">发布</el-button>
              <el-button v-if="row.status === 'PENDING'" link type="danger" @click="doReject(row)">驳回</el-button>
            </template>
            <el-button link type="danger" @click="doDelete(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-pagination class="pager" layout="total, prev, pager, next" :total="total"
                     :page-size="query.size" v-model:current-page="query.page" @current-change="load" />
    </el-card>

    <!-- 编辑弹窗 -->
    <el-dialog v-model="editVisible" :title="editForm.id ? '编辑知识' : '新建知识'" width="640px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="标题" required>
          <el-input v-model="editForm.title" maxlength="128" show-word-limit />
        </el-form-item>
        <el-form-item label="设备类型">
          <el-select v-model="editForm.applyDeviceType" clearable style="width: 200px">
            <el-option v-for="d in deviceTypes" :key="d" :label="d" :value="d" />
          </el-select>
        </el-form-item>
        <el-form-item label="分类">
          <el-select v-model="editForm.categoryId" clearable style="width: 200px">
            <el-option v-for="c in categories" :key="c.id" :label="c.categoryName" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="editForm.summary" type="textarea" :rows="2" maxlength="512" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="editForm.tagsText" placeholder="逗号分隔，如：贴片机,抛料,吸嘴" />
        </el-form-item>
        <el-form-item label="正文" required>
          <el-input v-model="editForm.content" type="textarea" :rows="8" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editVisible = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>

    <!-- 查看弹窗 -->
    <el-dialog v-model="viewVisible" :title="viewRow?.title" width="640px">
      <el-descriptions :column="2" size="small" border class="mb12">
        <el-descriptions-item label="设备类型">{{ viewRow?.applyDeviceType || '-' }}</el-descriptions-item>
        <el-descriptions-item label="分类">{{ categoryName(viewRow?.categoryId) }}</el-descriptions-item>
        <el-descriptions-item label="状态" :span="2">{{ statusMap[viewRow?.status] || viewRow?.status }}</el-descriptions-item>
        <el-descriptions-item label="标签" :span="2">
          <el-tag v-for="t in parseTags(viewRow?.tags)" :key="t" size="small" class="mr4">{{ t }}</el-tag>
        </el-descriptions-item>
        <el-descriptions-item v-if="viewRow?.sourceTicketId" label="来源工单" :span="2">
          {{ viewRow.sourceTicketId }}
        </el-descriptions-item>
      </el-descriptions>
      <p v-if="viewRow?.summary" class="summary">{{ viewRow.summary }}</p>
      <div class="content">{{ viewRow?.content }}</div>
      <div v-if="viewRow?.rejectReason" class="reject">驳回原因：{{ viewRow.rejectReason }}</div>
    </el-dialog>

    <!-- M6 抽取详情 -->
    <el-dialog v-model="extractViewVisible" :title="extractView?.title || '抽取详情'" width="720px">
      <el-descriptions :column="2" size="small" border class="mb12">
        <el-descriptions-item label="来源工单">{{ extractView?.sourceTicketNo || '-' }}</el-descriptions-item>
        <el-descriptions-item label="设备类型">{{ extractView?.deviceType || '-' }}</el-descriptions-item>
        <el-descriptions-item label="相似度">
          {{ extractView?.dedupScore != null ? Number(extractView.dedupScore).toFixed(4) : '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="处置建议">{{ suggestMap[extractView?.dedupAction] || '-' }}</el-descriptions-item>
        <el-descriptions-item label="相似条目" :span="2">{{ extractView?.dedupTargetTitle || '无' }}</el-descriptions-item>
        <el-descriptions-item label="相似度与关键差异" :span="2">
          {{ extractView?.dedupNote || '-' }}
        </el-descriptions-item>
        <el-descriptions-item label="抽取模型" :span="2">{{ extractView?.model || '-' }}</el-descriptions-item>
        <el-descriptions-item v-if="extractView?.errorMsg" label="失败原因" :span="2">
          {{ extractView.errorMsg }}
        </el-descriptions-item>
      </el-descriptions>
      <h4>故障现象</h4>
      <div class="content">{{ extractView?.faultPhenomenon || '-' }}</div>
      <h4>排查步骤</h4>
      <div class="content">{{ extractView?.troubleshootSteps || '-' }}</div>
      <h4>解决步骤</h4>
      <div class="content">{{ extractView?.solutionSteps || '-' }}</div>
      <h4>关键要点</h4>
      <div class="content">{{ extractView?.keyPoints || '-' }}</div>
      <h4>标签</h4>
      <el-tag v-for="t in parseTags(extractView?.tags)" :key="t" size="small" class="mr4">{{ t }}</el-tag>
    </el-dialog>

    <!-- M6 人工补录 -->
    <el-dialog v-model="extractEditVisible" title="人工补录 / 编辑抽取结果" width="680px">
      <el-form :model="extractForm" label-width="90px">
        <el-form-item label="标题" required>
          <el-input v-model="extractForm.title" maxlength="128" show-word-limit />
        </el-form-item>
        <el-form-item label="设备类型">
          <el-input v-model="extractForm.deviceType" style="width: 220px" />
        </el-form-item>
        <el-form-item label="标签">
          <el-input v-model="extractForm.tagsText" placeholder="逗号分隔，如：MES终端,接口超时" />
        </el-form-item>
        <el-form-item label="故障现象">
          <el-input v-model="extractForm.faultPhenomenon" type="textarea" :rows="2" />
        </el-form-item>
        <el-form-item label="排查步骤">
          <el-input v-model="extractForm.troubleshootSteps" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="解决步骤">
          <el-input v-model="extractForm.solutionSteps" type="textarea" :rows="3" />
        </el-form-item>
        <el-form-item label="关键要点">
          <el-input v-model="extractForm.keyPoints" type="textarea" :rows="2" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="extractEditVisible = false">取消</el-button>
        <el-button type="primary" :loading="extractSaving" @click="saveExtractEdit">保存补录</el-button>
      </template>
    </el-dialog>

    <!-- M6 合并确认（必须人工点击；先留全量快照，再由人工选择正文取舍） -->
    <el-dialog v-model="mergeVisible" title="确认合并到已有条目" width="880px">
      <el-alert type="warning" :closable="false" show-icon class="mb12"
                title="合并前会先写入原条目全量历史快照；正文保留方式由你选择，不会静默覆盖。" />
      <el-form label-width="110px">
        <el-form-item label="目标条目ID">
          <el-input-number v-model="mergeForm.targetId" :min="1" :controls="false" />
          <el-button link type="primary" class="ml8" :loading="mergePreviewLoading"
                     @click="verifyMergeTarget">校验目标并预览</el-button>
        </el-form-item>
        <el-form-item label="目标条目">{{ mergeTargetTitle || '请校验目标条目' }}</el-form-item>
        <el-form-item label="相似度">
          {{ (mergePreview?.dedupScore ?? mergeRow?.dedupScore) != null
            ? Number(mergePreview?.dedupScore ?? mergeRow?.dedupScore).toFixed(4) : '-' }}
        </el-form-item>
        <el-form-item label="关键差异">
          <span class="diff">{{ mergePreview?.dedupNote || mergeRow?.dedupNote || '-' }}</span>
        </el-form-item>
        <el-form-item label="正文取舍">
          <el-radio-group v-model="mergeForm.mode">
            <el-radio-button value="CONCAT">两者拼接（默认）</el-radio-button>
            <el-radio-button value="KEEP_ORIGINAL">保留原正文</el-radio-button>
            <el-radio-button value="REPLACE">用新内容替换</el-radio-button>
          </el-radio-group>
        </el-form-item>
      </el-form>
      <div v-if="mergePreview" class="diff-grid">
        <div class="diff-pane">
          <h4>原条目正文（v{{ mergePreview.targetVersion }}）</h4>
          <pre class="diff-pre">{{ mergePreview.targetContent || '（空）' }}</pre>
        </div>
        <div class="diff-pane">
          <h4>本次抽取新内容</h4>
          <pre class="diff-pre">{{ mergePreview.newContent }}</pre>
        </div>
      </div>
      <div v-if="selectedMergeOption" class="diff-result">
        <h4>合并后正文预览（{{ selectedMergeOption.label }}）</h4>
        <pre class="diff-pre">{{ selectedMergeOption.resultContent || '（空）' }}</pre>
      </div>
      <template #footer>
        <el-button @click="mergeVisible = false">取消</el-button>
        <el-button type="warning" :loading="mergeSaving" @click="doMergeExtract">确认合并</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  pageKnowledge, createKnowledge, updateKnowledge, deleteKnowledge,
  submitKnowledge, publishKnowledge, rejectKnowledge, listCategories, searchKnowledge,
  pageExtraction, updateExtraction, approveExtraction, mergeExtraction,
  previewMergeExtraction, rejectExtraction
} from '../api/kb'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
// 审核权限：管理员 + 审核员（既有 ADMIN 能力不回归）
const canReview = computed(() => {
  const roles = auth.user?.roles || []
  return roles.includes('ADMIN') || roles.includes('REVIEWER')
})

const statusMap = { DRAFT: '草稿', PENDING: '待审核', PUBLISHED: '已发布', REJECTED: '已驳回' }
function statusType(s) {
  return { DRAFT: 'info', PENDING: 'warning', PUBLISHED: 'success', REJECTED: 'danger' }[s] || 'info'
}
const deviceTypes = ['贴片机', 'AOI检测机', '涂布机', '贴合机', '蚀刻机']

function parseTags(tags) {
  if (!tags) return []
  if (Array.isArray(tags)) return tags
  try { return JSON.parse(tags) } catch (_) { return [] }
}

// 列表
const records = ref([])
const total = ref(0)
const loading = ref(false)
const query = reactive({ page: 1, size: 10, status: '', deviceType: '', keyword: '' })
const categories = ref([])

function categoryName(id) {
  const c = categories.value.find(x => x.id === id)
  return c ? c.categoryName : (id ? id : '-')
}

async function load() {
  loading.value = true
  try {
    const data = await pageKnowledge({ ...query })
    records.value = data.records
    total.value = data.total
  } finally {
    loading.value = false
  }
}

// 编辑
const editVisible = ref(false)
const saving = ref(false)
const editForm = reactive({ id: null, title: '', content: '', summary: '', tagsText: '', applyDeviceType: '', categoryId: null })

function openEdit(row) {
  editForm.id = row?.id || null
  editForm.title = row?.title || ''
  editForm.content = row?.content || ''
  editForm.summary = row?.summary || ''
  editForm.tagsText = parseTags(row?.tags).join(',')
  editForm.applyDeviceType = row?.applyDeviceType || ''
  editForm.categoryId = row?.categoryId || null
  editVisible.value = true
}

async function save() {
  if (!editForm.title.trim() || !editForm.content.trim()) {
    ElMessage.warning('标题与正文必填')
    return
  }
  saving.value = true
  try {
    const body = {
      title: editForm.title, content: editForm.content, summary: editForm.summary,
      tags: JSON.stringify(editForm.tagsText.split(/[,，]/).map(s => s.trim()).filter(Boolean)),
      applyDeviceType: editForm.applyDeviceType || null, categoryId: editForm.categoryId
    }
    if (editForm.id) {
      await updateKnowledge(editForm.id, body)
      ElMessage.success('已保存（版本 +1，已发布的知识会自动重新向量化）')
    } else {
      await createKnowledge(body)
      ElMessage.success('已创建草稿')
    }
    editVisible.value = false
    load()
  } finally {
    saving.value = false
  }
}

// 状态操作
async function doSubmit(row) {
  await submitKnowledge(row.id)
  ElMessage.success('已提交审核')
  load()
}
async function doPublish(row) {
  await publishKnowledge(row.id)
  ElMessage.success('已发布，30 秒内可被检索')
  load()
}
async function doReject(row) {
  const { value } = await ElMessageBox.prompt('请输入驳回原因', '驳回', { inputValue: '' })
  await rejectKnowledge(row.id, value)
  ElMessage.success('已驳回')
  load()
}
async function doDelete(row) {
  await ElMessageBox.confirm(`确认删除知识「${row.title}」？`, '删除', { type: 'warning' })
  await deleteKnowledge(row.id)
  ElMessage.success('已删除')
  load()
}

// 查看
const viewRow = ref(null)
const viewVisible = computed({
  get: () => !!viewRow.value,
  set: (v) => { if (!v) viewRow.value = null }
})

// 检索面板
const searchForm = reactive({ query: '', mode: 'HYBRID', topK: 5 })
const searching = ref(false)
const searchResult = ref(null)

async function doSearch() {
  if (!searchForm.query.trim()) {
    ElMessage.warning('请输入检索词')
    return
  }
  searching.value = true
  try {
    searchResult.value = await searchKnowledge({ ...searchForm })
    if (searchResult.value.fallback) {
      ElMessage.warning('Milvus 不可用，本次结果来自关键词降级')
    }
  } finally {
    searching.value = false
  }
}

// ---- M6 抽取审核中心（仅建议，人工确认后执行） ----
const extractStatusMap = {
  PENDING_REVIEW: '待审核', MANUAL_REQUIRED: '待补录', APPROVED: '已通过', MERGED: '已合并', REJECTED: '已驳回'
}
function extractStatusType(s) {
  return { PENDING_REVIEW: 'warning', MANUAL_REQUIRED: 'danger', APPROVED: 'success', MERGED: 'success', REJECTED: 'info' }[s] || 'info'
}
const suggestMap = { NEW: '建议新建', MERGE: '建议合并', SKIP: '建议跳过' }
function suggestType(a) {
  return { NEW: 'info', MERGE: 'warning', SKIP: 'danger' }[a] || 'info'
}
function pendingExtract(row) {
  return row && (row.status === 'PENDING_REVIEW' || row.status === 'MANUAL_REQUIRED')
}

const extractRecords = ref([])
const extractTotal = ref(0)
const extractLoading = ref(false)
const extractQuery = reactive({ page: 1, size: 10, status: 'PENDING_REVIEW' })

async function loadExtraction() {
  extractLoading.value = true
  try {
    const data = await pageExtraction({ ...extractQuery })
    extractRecords.value = data.records
    extractTotal.value = data.total
  } finally {
    extractLoading.value = false
  }
}

const extractView = ref(null)
const extractViewVisible = computed({
  get: () => !!extractView.value,
  set: (v) => { if (!v) extractView.value = null }
})

async function openExtractView(row) {
  extractView.value = await getExtraction(row.id)
}

const extractEditVisible = ref(false)
const extractSaving = ref(false)
const extractForm = reactive({
  id: null, title: '', deviceType: '', tagsText: '', faultPhenomenon: '',
  troubleshootSteps: '', solutionSteps: '', keyPoints: ''
})

function openExtractEdit(row) {
  extractForm.id = row.id
  extractForm.title = row.title || ''
  extractForm.deviceType = row.deviceType || ''
  extractForm.tagsText = parseTags(row.tags).join(',')
  extractForm.faultPhenomenon = row.faultPhenomenon || ''
  extractForm.troubleshootSteps = row.troubleshootSteps || ''
  extractForm.solutionSteps = row.solutionSteps || ''
  extractForm.keyPoints = row.keyPoints || ''
  extractEditVisible.value = true
}

async function saveExtractEdit() {
  if (!extractForm.title.trim()) {
    ElMessage.warning('标题必填')
    return
  }
  extractSaving.value = true
  try {
    await updateExtraction(extractForm.id, {
      title: extractForm.title,
      deviceType: extractForm.deviceType,
      tags: JSON.stringify(extractForm.tagsText.split(/[,，]/).map(s => s.trim()).filter(Boolean)),
      faultPhenomenon: extractForm.faultPhenomenon,
      troubleshootSteps: extractForm.troubleshootSteps,
      solutionSteps: extractForm.solutionSteps,
      keyPoints: extractForm.keyPoints
    })
    ElMessage.success('已保存补录，状态转为待审核')
    extractEditVisible.value = false
    loadExtraction()
  } finally {
    extractSaving.value = false
  }
}

async function doApproveExtract(row) {
  await ElMessageBox.confirm(
    `确认通过「${row.title}」并写入知识库？通过后 30 秒内可被检索。`, '人工确认新建', { type: 'warning' })
  await approveExtraction(row.id)
  ElMessage.success('已通过并写入知识库')
  loadExtraction()
  load()
}

async function doRejectExtract(row) {
  const { value } = await ElMessageBox.prompt('请输入驳回/跳过原因', '人工驳回', { inputValue: '' })
  await rejectExtraction(row.id, value)
  ElMessage.success('已驳回')
  loadExtraction()
}

const mergeVisible = ref(false)
const mergeSaving = ref(false)
const mergePreviewLoading = ref(false)
const mergeRow = ref(null)
const mergeTargetTitle = ref('')
const mergePreview = ref(null)
const mergeForm = reactive({ targetId: null, mode: 'CONCAT' })

const selectedMergeOption = computed(() =>
  mergePreview.value?.options?.find(o => o.mode === mergeForm.mode) || null)

function openMerge(row) {
  mergeRow.value = row
  mergeForm.targetId = row.dedupTargetId || null
  mergeForm.mode = 'CONCAT'
  mergeTargetTitle.value = row.dedupTargetTitle || ''
  mergePreview.value = null
  mergeVisible.value = true
  if (mergeForm.targetId) loadMergePreview()
}

async function loadMergePreview() {
  mergePreviewLoading.value = true
  try {
    const p = await previewMergeExtraction(mergeRow.value.id, mergeForm.targetId)
    mergePreview.value = p
    mergeTargetTitle.value = p.targetTitle
  } catch (_) {
    mergePreview.value = null
    mergeTargetTitle.value = ''
    ElMessage.error('目标条目不存在或不可合并（仅支持已发布条目）')
  } finally {
    mergePreviewLoading.value = false
  }
}

async function verifyMergeTarget() {
  if (!mergeForm.targetId) {
    ElMessage.warning('请输入目标条目ID')
    return
  }
  await loadMergePreview()
}

async function doMergeExtract() {
  if (!mergeForm.targetId) {
    ElMessage.warning('请输入目标条目ID')
    return
  }
  const modeLabel = selectedMergeOption.value?.label || mergeForm.mode
  await ElMessageBox.confirm(
    `确认将「${mergeRow.value?.title}」合并到 #${mergeForm.targetId}？\n正文取舍：${modeLabel}。\n原条目会先写入全量历史快照，动作类型会记录为 ${mergeForm.mode}。`,
    '人工确认合并', { type: 'warning' })
  mergeSaving.value = true
  try {
    await mergeExtraction(mergeRow.value.id, mergeForm.targetId, mergeForm.mode)
    ElMessage.success(`已合并（${modeLabel}），原条目已留历史快照`)
    mergeVisible.value = false
    loadExtraction()
    load()
  } finally {
    mergeSaving.value = false
  }
}

onMounted(async () => {
  load()
  loadExtraction()
  try { categories.value = await listCategories() } catch (_) { /* 分类加载失败不阻塞 */ }
})
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.mt12 { margin-top: 12px; }
.mr4 { margin-right: 4px; }
.mr8 { margin-right: 8px; }
.ml8 { margin-left: 8px; }
.score { color: #409eff; margin-right: 6px; }
.target { color: #909399; font-size: 12px; }
.diff { color: #606266; font-size: 12px; line-height: 1.6; }
.diff-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 12px; }
.diff-pane, .diff-result { border: 1px solid #ebeef5; border-radius: 4px; padding: 8px; }
.diff-pre { max-height: 180px; overflow: auto; white-space: pre-wrap; font-size: 12px; line-height: 1.6; margin: 0; background: #f5f7fa; padding: 8px; border-radius: 4px; }
h4 { margin: 12px 0 4px; font-size: 13px; color: #303133; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.search-bar { display: flex; gap: 10px; align-items: center; }
.filters { display: flex; gap: 8px; margin-bottom: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.summary { color: #606266; background: #f5f7fa; padding: 8px; border-radius: 4px; }
.content { white-space: pre-wrap; line-height: 1.7; margin-top: 8px; }
.reject { color: #f56c6c; margin-top: 8px; }
</style>
