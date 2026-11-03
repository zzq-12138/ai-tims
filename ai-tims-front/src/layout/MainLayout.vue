<template>
  <el-container class="layout">
    <el-aside width="200px" class="aside">
      <div class="logo">AI-TIMS</div>
      <el-menu :default-active="route.path" router background-color="#1f2d3d"
               text-color="#cfd8e3" active-text-color="#409eff">
        <el-menu-item index="/dashboard">
          <span>工作台</span>
        </el-menu-item>
        <el-menu-item index="/tickets">
          <span>工单管理</span>
        </el-menu-item>
        <el-menu-item v-if="isAdmin" index="/system/users">
          <span>系统管理</span>
        </el-menu-item>
        <el-menu-item index="/kb">
          <span>知识库</span>
        </el-menu-item>
      </el-menu>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div />
        <el-dropdown @command="onCommand">
          <span class="user">{{ auth.user?.nickname || '用户' }}</span>
          <template #dropdown>
            <el-dropdown-menu>
              <el-dropdown-item command="logout">退出登录</el-dropdown-item>
            </el-dropdown-menu>
          </template>
        </el-dropdown>
      </el-header>
      <el-main>
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { logout } from '../api/auth'
import { useAuthStore } from '../stores/auth'

const route = useRoute()
const router = useRouter()
const auth = useAuthStore()
const isAdmin = computed(() => (auth.user?.roles || []).includes('ADMIN'))

async function onCommand(cmd) {
  if (cmd === 'logout') {
    try { await logout() } catch (_) { /* 忽略登出接口异常，本地照常清理 */ }
    auth.clear()
    router.push('/login')
  }
}
</script>

<style scoped>
.layout { height: 100vh; }
.aside { background-color: #1f2d3d; }
.logo {
  height: 56px;
  line-height: 56px;
  text-align: center;
  color: #fff;
  font-weight: 600;
  letter-spacing: 2px;
}
.header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  border-bottom: 1px solid #e4e7ed;
}
.user { cursor: pointer; }
</style>
