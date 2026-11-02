<template>
  <div>
    <el-card>
      <template #header>工作台</template>
      <p>欢迎，{{ auth.user?.nickname }}（租户 {{ auth.user?.tenantId }}，角色：{{ roles }}）</p>
      <p>M1 骨架：登录/鉴权链路已通；工单（M2）、知识库（M3）模块开发中。</p>
    </el-card>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const roles = computed(() => (auth.user?.roles || []).join(', ') || '—')
</script>
