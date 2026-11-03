<template>
  <el-card shadow="never">
    <template #header>新建工单</template>
    <el-form :model="form" label-width="100px" style="max-width: 720px">
      <el-form-item label="工单名称" required>
        <el-input v-model="form.title" maxlength="128" placeholder="一句话概括异常" />
      </el-form-item>
      <el-form-item label="工单类型" required>
        <el-select v-model="form.ticketType" style="width: 220px">
          <el-option v-for="t in types" :key="t" :label="t" :value="t" />
        </el-select>
      </el-form-item>
      <el-form-item label="紧急程度">
        <el-radio-group v-model="form.urgency">
          <el-radio :value="1">高</el-radio>
          <el-radio :value="2">中</el-radio>
          <el-radio :value="3">低</el-radio>
        </el-radio-group>
      </el-form-item>
      <el-form-item label="厂区">
        <el-input v-model="form.factory" style="width: 220px" placeholder="如 F1" />
      </el-form-item>
      <el-form-item label="设备类型">
        <el-select v-model="form.deviceType" clearable style="width: 220px">
          <el-option v-for="d in devices" :key="d" :label="d" :value="d" />
        </el-select>
      </el-form-item>
      <el-form-item label="Glass ID">
        <el-input v-model="form.glassId" style="width: 220px" placeholder="可空" />
      </el-form-item>
      <el-form-item label="现象描述" required>
        <el-input v-model="form.description" type="textarea" :rows="4" placeholder="异常现象、影响范围、已尝试的措施…" />
      </el-form-item>
      <el-form-item>
        <el-button type="primary" :loading="saving" @click="save(false)">提交工单</el-button>
        <el-button :loading="saving" @click="save(true)">存草稿</el-button>
      </el-form-item>
    </el-form>
  </el-card>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { createTicket } from '../api/ticket'

const router = useRouter()
const saving = ref(false)
const types = ['设备异常', '品质异常', '系统异常', '其他']
const devices = ['贴片机', 'AOI检测机', '涂布机', '贴合机', '蚀刻机']

const form = reactive({
  title: '', ticketType: '', urgency: 2, factory: 'F1',
  deviceType: '', glassId: '', description: ''
})

async function save(draft) {
  if (!form.title.trim() || !form.ticketType || !form.description.trim()) {
    ElMessage.warning('请填写工单名称、类型与现象描述')
    return
  }
  saving.value = true
  try {
    const t = await createTicket({ ...form, draft })
    ElMessage.success(draft ? '草稿已保存' : '工单已提交')
    router.push(`/tickets/${t.id}`)
  } catch (e) {
    ElMessage.error(e.message || '提交失败')
  } finally {
    saving.value = false
  }
}
</script>
