<template>
  <div>
    <el-card shadow="never">
      <div class="toolbar">
        <el-tabs v-model="tab" @tab-change="load">
          <el-tab-pane label="待办" name="TODO" />
          <el-tab-pane label="我处理的" name="DONE" />
          <el-tab-pane label="我发起的" name="MINE" />
          <el-tab-pane label="全部" name="ALL" />
        </el-tabs>
        <div class="filters">
          <el-input v-model="query.keyword" placeholder="编号/标题/描述" clearable style="width: 180px" @keyup.enter="load" />
          <el-select v-model="query.status" placeholder="状态" clearable style="width: 130px">
            <el-option v-for="(v, k) in statusMap" :key="k" :label="v" :value="k" />
          </el-select>
          <el-select v-model="query.ticketType" placeholder="类型" clearable style="width: 130px">
            <el-option v-for="t in types" :key="t" :label="t" :value="t" />
          </el-select>
          <el-button type="primary" @click="load">查询</el-button>
          <el-button type="success" @click="$router.push('/tickets/create')">新建工单</el-button>
        </div>
      </div>

      <el-table :data="records" v-loading="loading" stripe>
        <el-table-column prop="ticketNo" label="工单编号" width="180" />
        <el-table-column prop="title" label="标题" min-width="200" show-overflow-tooltip />
        <el-table-column prop="ticketType" label="类型" width="100" />
        <el-table-column prop="deviceType" label="设备类型" width="110" />
        <el-table-column prop="factory" label="厂区" width="70" />
        <el-table-column label="紧急" width="70">
          <template #default="{ row }">
            <el-tag :type="row.urgency === 1 ? 'danger' : row.urgency === 2 ? 'warning' : 'info'" size="small">
              {{ { 1: '高', 2: '中', 3: '低' }[row.urgency] }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="状态" width="90">
          <template #default="{ row }">
            <el-tag :type="statusType(row.status)" size="small">{{ statusMap[row.status] || row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="handlerName" label="处理人" width="100" />
        <el-table-column prop="createTime" label="创建时间" width="170" />
        <el-table-column label="操作" width="90" fixed="right">
          <template #default="{ row }">
            <el-button link type="primary" @click="$router.push(`/tickets/${row.id}`)">详情</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination class="pager" layout="total, prev, pager, next" :total="total"
                     :page-size="query.size" v-model:current-page="query.page" @current-change="load" />
    </el-card>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { pageTickets } from '../api/ticket'
import { onPush } from '../utils/ws'

const tab = ref('ALL')
const records = ref([])
const total = ref(0)
const loading = ref(false)
const query = reactive({ page: 1, size: 10, keyword: '', status: '', ticketType: '' })
const types = ['设备异常', '品质异常', '系统异常', '其他']
const statusMap = {
  DRAFT: '草稿', SUBMITTED: '待受理', ACCEPTED: '已受理', PROCESSING: '处理中',
  SUSPENDED: '挂起', RESOLVED: '待验证', CLOSED: '已关闭', TERMINATED: '已终止'
}
function statusType(s) {
  return { SUBMITTED: 'warning', ACCEPTED: 'primary', PROCESSING: 'primary', SUSPENDED: 'info',
    RESOLVED: 'success', CLOSED: 'success', TERMINATED: 'danger', DRAFT: 'info' }[s] || 'info'
}

async function load() {
  loading.value = true
  try {
    const data = await pageTickets({ ...query, tab: tab.value })
    records.value = data.records
    total.value = data.total
  } finally {
    loading.value = false
  }
}

// M4：推送实时反映——新工单卡片/关闭通知到达时自动刷新当前列表（1s 去抖）
let reloadTimer = null
function scheduleReload(reason) {
  if (reloadTimer) return
  reloadTimer = setTimeout(() => {
    reloadTimer = null
    load()
  }, 1000)
}
const offCard = onPush('CARD', (c) => {
  scheduleReload()
  if (c?.ticketNo) ElMessage.info(`新工单 ${c.ticketNo} 已进入列表`)
})
const offClosed = onPush('TICKET_CLOSED', () => scheduleReload())
onMounted(() => { load(); })
onUnmounted(() => { offCard(); offClosed(); if (reloadTimer) clearTimeout(reloadTimer) })
</script>

<style scoped>
.toolbar { display: flex; justify-content: space-between; align-items: center; flex-wrap: wrap; }
.filters { display: flex; gap: 8px; margin-bottom: 12px; }
.pager { margin-top: 12px; justify-content: flex-end; }
</style>
