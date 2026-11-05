<template>
  <div>
    <el-card>
      <template #header>工作台</template>
      <p>欢迎，{{ auth.user?.nickname }}（租户 {{ auth.user?.tenantId }}，角色：{{ roles }}）</p>
      <p>工单管理、知识库检索与 AI 助手均已就绪；实时消息请从顶栏「消息中心」查看。</p>
    </el-card>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { useAuthStore } from '../stores/auth'

const auth = useAuthStore()
const roles = computed(() => (auth.user?.roles || []).join(', ') || '—')
</script>
