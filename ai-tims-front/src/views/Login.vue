<template>
  <div class="auth-canvas login-shell">
    <!-- 背景层：品牌信息悬浮在工作面背景上 -->
    <aside class="brand-panel">
      <div class="brand-top">
        <span class="brand-chip">AI-TIMS · 智能工单闭环</span>
        <span class="brand-date">2026</span>
      </div>

      <div class="brand-core">
        <div class="brand-eyebrow">INDUSTRIAL TICKET · KNOWLEDGE LOOP</div>
        <div class="brand-wordmark">AI-TIMS</div>
        <div class="brand-rule" />
        <p class="brand-line">
          从现场报障到知识沉淀，一条不丢信息的闭环。<br />
          工单流转、混合检索、AI 抽取审核在同一张工作面上完成。
        </p>
      </div>

      <div class="brand-list">
        <div class="brand-item">
          <span class="brand-no">01</span>
          <span class="brand-item-text">工单全生命周期与实时消息</span>
        </div>
        <div class="brand-item">
          <span class="brand-no">02</span>
          <span class="brand-item-text">RBAC 四角色权限矩阵</span>
        </div>
        <div class="brand-item">
          <span class="brand-no">03</span>
          <span class="brand-item-text">抽取 → 人工审核 → 再命中</span>
        </div>
      </div>

      <div class="brand-foot">
        <span>Spring Cloud Gateway</span>
        <span>Sa-Token</span>
        <span>Milvus</span>
      </div>
    </aside>

    <!-- 表单浮层：偏右、不贴边、圆角卡片 -->
    <main class="form-layer">
      <el-card class="form-card" shadow="never">
        <div class="form-inner">
          <div class="form-eyebrow">SIGN IN</div>
          <h1 class="form-title">登录工作面</h1>
          <p class="form-sub">使用工号账号进入工单与知识闭环系统</p>

          <el-alert
            v-if="errMsg"
            :title="errMsg"
            type="error"
            show-icon
            :closable="false"
            class="form-alert"
          />

          <el-form :model="form" class="form-body" @keyup.enter="onLogin">
            <el-form-item label="账号">
              <el-input v-model="form.username" placeholder="用户名" size="large" />
            </el-form-item>
            <el-form-item label="口令">
              <el-input v-model="form.password" type="password" placeholder="密码" size="large" show-password />
            </el-form-item>
            <el-form-item class="remember-row">
              <el-checkbox v-model="remember" @change="onRememberChange">记住密码</el-checkbox>
              <span class="remember-hint">仅保存在本机浏览器</span>
            </el-form-item>
            <el-form-item class="form-submit">
              <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="onLogin">
                登 录
              </el-button>
            </el-form-item>
          </el-form>

          <div class="to-register">还没有账号？<router-link to="/register">立即注册</router-link></div>
          <div class="form-note">报障人仅可见本人创建的工单；审核员负责知识发布与抽取审核。</div>
        </div>
      </el-card>
    </main>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { login, me } from '../api/auth'
import { useAuthStore } from '../stores/auth'

// 记住密码：账号长期保留；密码仅在勾选时保留。
// 存储取舍：localStorage 明文（同源脚本可读，存在 XSS 泄露风险），不做“看起来加密”的假安全；
// 本机演示场景可接受，敏感环境应改为服务端会话或一次性令牌。
const REMEMBER_USER_KEY = 'tims_remember_user'
const REMEMBER_PWD_KEY = 'tims_remember_password'

const router = useRouter()
const route = useRoute()
const auth = useAuthStore()
const loading = ref(false)
const errMsg = ref('')

const savedUser = localStorage.getItem(REMEMBER_USER_KEY) || ''
const savedPwd = localStorage.getItem(REMEMBER_PWD_KEY) || ''
const form = reactive({ username: savedUser, password: savedPwd })
const remember = ref(!!savedPwd)

function onRememberChange(val) {
  // 取消勾选立即清除密码留存；账号保留以便下次只回填账号
  if (!val) localStorage.removeItem(REMEMBER_PWD_KEY)
}

function persistRemember() {
  localStorage.setItem(REMEMBER_USER_KEY, form.username)
  if (remember.value) {
    localStorage.setItem(REMEMBER_PWD_KEY, form.password)
  } else {
    localStorage.removeItem(REMEMBER_PWD_KEY)
  }
}

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
    persistRemember()
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
.login-shell {
  position: relative;
  display: grid;
  grid-template-columns: minmax(0, 1fr) auto;
  align-items: center;
  gap: 32px;
  min-height: 100vh;
  padding: clamp(24px, 4vw, 56px);
}

/* ---------- 品牌侧（背景的一部分，不再独占一列深色块） ---------- */
.brand-panel {
  max-width: 460px;
  display: flex;
  flex-direction: column;
  gap: 34px;
  color: #e8e3da;
  animation: rise .6s ease both;
}
.brand-top {
  display: flex;
  align-items: center;
  gap: 16px;
}
.brand-chip {
  padding: 5px 10px;
  border: 1px solid rgba(180, 90, 30, .55);
  border-radius: 4px;
  color: #e0a878;
  font-size: 11px;
  letter-spacing: .14em;
}
.brand-date {
  font-family: var(--font-mono);
  font-size: 12px;
  color: #78838d;
  letter-spacing: .2em;
}
.brand-eyebrow {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: .26em;
  color: #8d99a3;
}
.brand-wordmark {
  margin: 14px 0 0;
  font-family: var(--font-display);
  font-size: clamp(52px, 6.6vw, 86px);
  font-weight: 700;
  line-height: .95;
  letter-spacing: .06em;
  color: #f3ede3;
  text-shadow: 0 22px 50px rgba(0, 0, 0, .55);
}
.brand-rule {
  width: 76px;
  height: 3px;
  margin: 22px 0 20px;
  background: var(--amber);
}
.brand-line {
  max-width: 430px;
  color: #a9b3bc;
  font-size: 13px;
  line-height: 1.85;
}
.brand-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.brand-item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 9px 0;
  border-top: 1px solid rgba(255, 255, 255, .08);
}
.brand-no {
  font-family: var(--font-mono);
  font-size: 11px;
  color: var(--amber);
  letter-spacing: .12em;
}
.brand-item-text { font-size: 13px; color: #c3cbd3; letter-spacing: .04em; }
.brand-foot {
  display: flex;
  gap: 18px;
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: .12em;
  color: #8d99a3;
}

/* ---------- 表单浮层 ---------- */
.form-layer {
  display: flex;
  justify-content: flex-end;
  align-items: center;
  width: 100%;
  padding-right: clamp(8px, 3vw, 48px);
}
.form-card {
  width: min(400px, 92vw);
  border-radius: 18px;
  border: 1px solid rgba(255, 255, 255, .55);
  background: rgba(255, 253, 249, .97);
  box-shadow: 0 34px 80px -34px rgba(0, 0, 0, .65), 0 2px 0 rgba(255, 255, 255, .4) inset;
  animation: rise .6s .12s ease both;
}
.form-card :deep(.el-card__body) { padding: 32px 30px 30px; }
.form-eyebrow {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: .3em;
  color: var(--amber);
}
.form-title {
  margin: 10px 0 6px;
  font-size: 27px;
  letter-spacing: .02em;
}
.form-sub { color: var(--muted); font-size: 12.5px; }
.form-alert { margin-top: 18px; }
.form-body { margin-top: 22px; }
.form-body :deep(.el-form-item) { margin-bottom: 16px; }
.form-body :deep(.el-form-item__label) { font-size: 12px; letter-spacing: .1em; color: var(--muted); }
.remember-row { margin-top: -4px; }
.remember-row :deep(.el-form-item__content) { align-items: center; gap: 10px; }
.remember-hint { color: var(--muted); font-size: 11px; }
.form-submit { margin-bottom: 8px; }
.submit-btn {
  width: 100%;
  height: 44px;
  letter-spacing: .28em;
  font-size: 14px;
}
.to-register { margin-top: 6px; font-size: 12.5px; color: var(--muted); }
.to-register a { color: var(--amber-deep); text-decoration: none; font-weight: 600; }
.to-register a:hover { text-decoration: underline; }
.form-note {
  margin-top: 26px;
  padding-top: 14px;
  border-top: 1px dashed var(--line);
  color: var(--muted);
  font-size: 11.5px;
  line-height: 1.7;
}

@keyframes rise {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 900px) {
  .login-shell {
    grid-template-columns: 1fr;
    align-content: center;
    justify-items: center;
    gap: 26px;
    padding: 26px 18px 34px;
  }
  .brand-panel { max-width: 420px; gap: 18px; }
  .brand-wordmark { font-size: 44px; }
  .brand-line { font-size: 12px; }
  .brand-list { display: none; }
  .brand-foot { display: none; }
  .form-layer { justify-content: center; padding-right: 0; }
  .form-card { width: min(420px, 100%); }
}
</style>
