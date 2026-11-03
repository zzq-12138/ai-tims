<template>
  <el-card shadow="never">
    <template #header>
      <div class="head">
        <span>用户管理（ADMIN）</span>
        <div class="filters">
          <el-input v-model="keyword" placeholder="用户名/姓名/手机/邮箱" clearable style="width: 200px" @keyup.enter="load" />
          <el-button type="primary" @click="load">查询</el-button>
          <el-button type="success" @click="openCreate">新增用户</el-button>
        </div>
      </div>
    </template>

    <el-table :data="records" v-loading="loading" stripe>
      <el-table-column prop="username" label="用户名" width="130" />
      <el-table-column prop="nickname" label="姓名" width="110" />
      <el-table-column prop="phone" label="手机号" width="130" />
      <el-table-column prop="email" label="邮箱" min-width="170" show-overflow-tooltip />
      <el-table-column prop="factory" label="厂区" width="70" />
      <el-table-column label="角色" min-width="150">
        <template #default="{ row }">
          <el-tag v-for="r in roleNames(row.roleIds)" :key="r" size="small" class="mr4">{{ r }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="80">
        <template #default="{ row }">
          <el-tag :type="row.status === 1 ? 'success' : 'danger'" size="small">
            {{ row.status === 1 ? '启用' : '停用' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="操作" width="130" fixed="right">
        <template #default="{ row }">
          <el-button link type="primary" @click="openEdit(row)">编辑</el-button>
          <el-popconfirm title="确认删除该用户？" @confirm="remove(row)">
            <template #reference><el-button link type="danger">删除</el-button></template>
          </el-popconfirm>
        </template>
      </el-table-column>
    </el-table>
    <el-pagination class="pager" layout="total, prev, pager, next" :total="total"
                   :page-size="size" v-model:current-page="page" @current-change="load" />

    <el-dialog v-model="dialog" :title="editing ? '编辑用户' : '新增用户'" width="480px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="用户名" required>
          <el-input v-model="form.username" :disabled="editing" />
        </el-form-item>
        <el-form-item label="姓名" required>
          <el-input v-model="form.nickname" />
        </el-form-item>
        <el-form-item label="密码" :required="!editing">
          <el-input v-model="form.password" type="password" show-password
                    :placeholder="editing ? '留空表示不修改' : '≥8位，含大小写+数字+特殊字符'" />
        </el-form-item>
        <el-form-item label="手机号"><el-input v-model="form.phone" /></el-form-item>
        <el-form-item label="邮箱"><el-input v-model="form.email" /></el-form-item>
        <el-form-item label="厂区"><el-input v-model="form.factory" style="width: 140px" /></el-form-item>
        <el-form-item label="部门">
          <el-tree-select v-model="form.deptId" :data="treeData" check-strictly style="width: 220px" />
        </el-form-item>
        <el-form-item label="角色">
          <el-select v-model="form.roleIds" multiple style="width: 100%">
            <el-option v-for="r in roles" :key="r.id" :label="r.roleName" :value="r.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="form.status" :active-value="1" :inactive-value="0" active-text="启用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="save">保存</el-button>
      </template>
    </el-dialog>
  </el-card>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { pageUsers, createUser, updateUser, deleteUser, listRoles, deptTree } from '../api/system'

const records = ref([])
const total = ref(0)
const loading = ref(false)
const keyword = ref('')
const page = ref(1)
const size = 10
const roles = ref([])
const dialog = ref(false)
const editing = ref(false)
const saving = ref(false)
const treeData = ref([])

const form = reactive({ id: null, username: '', nickname: '', password: '', phone: '', email: '', factory: '', deptId: null, roleIds: [], status: 1 })

function roleNames(ids) {
  return (ids || []).map((id) => roles.value.find((r) => r.id === id)?.roleName).filter(Boolean)
}

async function load() {
  loading.value = true
  try {
    const data = await pageUsers({ keyword: keyword.value, page: page.value, size })
    records.value = data.records
    total.value = data.total
  } finally {
    loading.value = false
  }
}

function openCreate() {
  editing.value = false
  Object.assign(form, { id: null, username: '', nickname: '', password: '', phone: '', email: '', factory: '', deptId: null, roleIds: [], status: 1 })
  dialog.value = true
}

function openEdit(row) {
  editing.value = true
  Object.assign(form, { ...row, password: '' })
  dialog.value = true
}

async function save() {
  if (!editing.value && (!form.username.trim() || !form.nickname.trim() || !form.password)) {
    ElMessage.warning('用户名、姓名、密码必填')
    return
  }
  saving.value = true
  try {
    if (editing.value) {
      await updateUser(form)
    } else {
      await createUser(form)
    }
    ElMessage.success('保存成功')
    dialog.value = false
    await load()
  } catch (e) {
    ElMessage.error(e.message || '保存失败')
  } finally {
    saving.value = false
  }
}

async function remove(row) {
  await deleteUser(row.id)
  ElMessage.success('已删除')
  await load()
}

function toTree(nodes) {
  return nodes.map((n) => ({
    value: n.id, label: n.deptName,
    children: n.children ? toTree(n.children) : undefined
  }))
}

onMounted(async () => {
  roles.value = await listRoles()
  treeData.value = toTree(await deptTree())
  await load()
})
</script>

<style scoped>
.head { display: flex; justify-content: space-between; align-items: center; }
.filters { display: flex; gap: 8px; }
.pager { margin-top: 12px; justify-content: flex-end; }
.mr4 { margin-right: 4px; }
</style>
