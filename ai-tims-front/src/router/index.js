import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/Login.vue') },
  { path: '/register', name: 'register', component: () => import('../views/Register.vue') },
  {
    path: '/',
    component: () => import('../layout/MainLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'dashboard',
        component: () => import('../views/Dashboard.vue'),
        meta: { title: '工作台' }
      },
      {
        path: 'tickets',
        name: 'tickets',
        component: () => import('../views/TicketList.vue'),
        meta: { title: '工单列表' }
      },
      {
        path: 'tickets/create',
        name: 'ticket-create',
        component: () => import('../views/TicketCreate.vue'),
        meta: { title: '新建工单' }
      },
      {
        path: 'tickets/:id',
        name: 'ticket-detail',
        component: () => import('../views/TicketDetail.vue'),
        meta: { title: '工单详情' }
      },
      {
        path: 'kb',
        name: 'kb',
        component: () => import('../views/Knowledge.vue'),
        meta: { title: '知识库', roles: ['ADMIN', 'ENGINEER', 'REVIEWER'] }
      },
      {
        path: 'assistant',
        name: 'assistant',
        component: () => import('../views/Assistant.vue'),
        meta: { title: 'AI 助手' }
      },
      {
        path: 'system/users',
        name: 'system-users',
        component: () => import('../views/SystemUser.vue'),
        meta: { title: '用户管理', roles: ['ADMIN'] }
      }
    ]
  },
  { path: '/:pathMatch(.*)*', redirect: '/dashboard' }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

// 路由守卫：无 token 一律回登录页（注册页除外）
router.beforeEach((to) => {
  const auth = useAuthStore()
  if (to.path !== '/login' && to.path !== '/register' && !auth.token) {
    return { path: '/login', query: { redirect: to.fullPath } }
  }
  if (to.path === '/login' && auth.token) {
    return { path: '/dashboard' }
  }
  // 角色矩阵：菜单/路由双重显隐，越权访问回到工作台
  if (to.meta?.roles) {
    const roles = auth.user?.roles || []
    if (!to.meta.roles.some(r => roles.includes(r))) {
      return { path: '/dashboard' }
    }
  }
})

export default router
