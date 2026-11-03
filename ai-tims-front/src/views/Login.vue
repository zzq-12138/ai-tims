<template>
  <div class="login-wrap">
    <el-card class="login-card">
      <h2 class="title">AI-TIMS 智能工单系统</h2>
      <el-alert
        v-if="errMsg"
        :title="errMsg"
        type="error"
        show-icon
        :closable="false"
        style="margin-bottom: 14px"
      />
      <el-form :model="form" @keyup.enter="onLogin">
        <el-form-item>
          <el-input v-model="form.username" placeholder="用户名" size="large" />
        </el-form-item>
        <el-form-item>
          <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" size="large" style="width: 100%" :loading="loading" @click="onLogin">
            登 录
          </el-button>
        </el-form-item>
      </el-form>
      <div class="to-register">还没有账号？<router-link to="/register">立即注册</router-link></div>
    </el-card>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, me } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const loading = ref(false)
const errMsg = ref('')
const form = reactive({ username: '', password: '' })

async function onLogin() {
  errMsg.value = ''
  if (!form.username || !form.password) {
    errMsg.value = '请输入用户名和密码'
    return
  }
  loading.value = true
  try {
    const data = await login(form.username, form.password)
    auth.setToken(data.token)
    const user = await me()
    auth.setUser(user)
    ElMessage.success('登录成功')
    router.push(route.query.redirect || '/dashboard')
  } catch (e) {
    errMsg.value = e.message || '登录失败，请稍后重试'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  height: 100vh;
  background: linear-gradient(135deg, #1f2d3d 0%, #2b4a6f 100%);
}
.login-card {
  width: 380px;
  padding: 8px 12px;
}
.title {
  text-align: center;
  margin: 8px 0 24px;
  color: #1f2d3d;
}
.to-register {
  text-align: center;
  font-size: 13px;
  color: #606266;
}
</style>
