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
            <template v-if="isAdmin">
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
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  pageKnowledge, createKnowledge, updateKnowledge, deleteKnowledge,
  submitKnowledge, publishKnowledge, rejectKnowledge, listCategories, searchKnowledge
} from '../api/kb'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const isAdmin = computed(() => (auth.user?.roles || []).includes('ADMIN'))

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

onMounted(async () => {
  load()
  try { categories.value = await listCategories() } catch (_) { /* 分类加载失败不阻塞 */ }
})
</script>

<style scoped>
.mb12 { margin-bottom: 12px; }
.mt12 { margin-top: 12px; }
.mr4 { margin-right: 4px; }
.card-head { display: flex; justify-content: space-between; align-items: center; }
.search-bar { display: flex; gap: 10px; align-items: center; }
.filters { display: flex; gap: 8px; margin-bottom: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.summary { color: #606266; background: #f5f7fa; padding: 8px; border-radius: 4px; }
.content { white-space: pre-wrap; line-height: 1.7; margin-top: 8px; }
.reject { color: #f56c6c; margin-top: 8px; }
</style>
