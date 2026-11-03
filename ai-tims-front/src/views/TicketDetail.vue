<template>
  <div v-if="detail">
    <el-card shadow="never">
      <template #header>
        <div class="head">
          <span>{{ detail.ticket.title }}</span>
          <div>
            <el-tag :type="statusType(detail.ticket.status)" class="mr8">{{ statusMap[detail.ticket.status] }}</el-tag>
            <el-button size="small" @click="$router.back()">返回</el-button>
          </div>
        </div>
      </template>

      <el-descriptions :column="3" border size="small">
        <el-descriptions-item label="工单编号">{{ detail.ticket.ticketNo || '-' }}</el-descriptions-item>
        <el-descriptions-item label="类型">{{ detail.ticket.ticketType }}</el-descriptions-item>
        <el-descriptions-item label="紧急程度">{{ { 1: '高', 2: '中', 3: '低' }[detail.ticket.urgency] }}</el-descriptions-item>
        <el-descriptions-item label="厂区/厂别">{{ detail.ticket.factory || '-' }} / {{ detail.ticket.plant || '-' }}</el-descriptions-item>
        <el-descriptions-item label="设备类型">{{ detail.ticket.deviceType || '-' }}</el-descriptions-item>
        <el-descriptions-item label="Glass ID">{{ detail.ticket.glassId || '-' }}</el-descriptions-item>
        <el-descriptions-item label="处理人">{{ detail.ticket.handlerName || '-' }}</el-descriptions-item>
        <el-descriptions-item label="创建时间">{{ detail.ticket.createTime }}</el-descriptions-item>
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
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  getTicket, ticketAction, addComment,
  listAttachments, uploadAttachment, downloadAttachment, deleteAttachment
} from '../api/ticket'

const route = useRoute()
const id = route.params.id
const detail = ref(null)
const acting = ref(false)
const comment = ref('')
const attachments = ref([])
const uploading = ref(false)

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
.head { display: flex; justify-content: space-between; align-items: center; }
.actions { margin: 16px 0; display: flex; gap: 8px; }
.muted { color: #909399; font-size: 12px; }
.comment { border-top: 1px dashed #e4e7ed; padding: 8px 0; }
.comment-input { margin-top: 12px; }
.mt8 { margin-top: 8px; }
.mr8 { margin-right: 8px; }
.attachments { margin: 8px 0 16px; }
.att-head { display: flex; justify-content: space-between; align-items: center; }
</style>
