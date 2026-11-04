<template>
  <div class="login-shell">
    <!-- 品牌侧：工业现场工作面 -->
    <aside class="brand-panel">
      <div class="brand-top">
        <span class="brand-chip">M6 · 知识提炼闭环</span>
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
          <span class="brand-item-text">工单全生命周期与实时推送</span>
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

    <!-- 表单侧：纸感凭证 -->
    <main class="form-panel">
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
          <el-form-item class="form-submit">
            <el-button type="primary" size="large" class="submit-btn" :loading="loading" @click="onLogin">
              登 录
            </el-button>
          </el-form-item>
        </el-form>

        <div class="to-register">还没有账号？<router-link to="/register">立即注册</router-link></div>
        <div class="form-note">报障人仅可见本人创建的工单；审核员负责知识发布与抽取审核。</div>
      </div>
    </main>
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
.login-shell {
  display: grid;
  grid-template-columns: minmax(420px, 1fr) 460px;
  min-height: 100vh;
  background: var(--paper);
}

/* ---------- 品牌侧 ---------- */
.brand-panel {
  position: relative;
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  gap: 32px;
  padding: 46px 54px 40px;
  overflow: hidden;
  color: #e8e3da;
  background:
    radial-gradient(1200px 600px at 18% 8%, rgba(180, 90, 30, .24), transparent 62%),
    linear-gradient(160deg, var(--graphite) 0%, #0d141a 100%);
}
.brand-panel::before {
  content: "";
  position: absolute;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255, 255, 255, .045) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255, 255, 255, .045) 1px, transparent 1px);
  background-size: 44px 44px;
  mask-image: radial-gradient(120% 90% at 20% 10%, #000 30%, transparent 78%);
}
.brand-panel::after {
  content: "";
  position: absolute;
  top: 0;
  right: 0;
  width: 3px;
  height: 100%;
  background: linear-gradient(180deg, var(--amber), rgba(180, 90, 30, 0));
}
.brand-top,
.brand-core,
.brand-list,
.brand-foot { position: relative; z-index: 1; }

.brand-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  animation: rise .6s ease both;
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
.brand-core { animation: rise .7s .12s ease both; }
.brand-eyebrow {
  font-family: var(--font-mono);
  font-size: 10.5px;
  letter-spacing: .26em;
  color: #8d99a3;
}
.brand-wordmark {
  margin: 14px 0 0;
  font-family: var(--font-display);
  font-size: clamp(56px, 7.4vw, 92px);
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
  animation: rise .7s .24s ease both;
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
  color: #5f6b76;
  animation: rise .7s .32s ease both;
}

/* ---------- 表单侧 ---------- */
.form-panel {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 48px 40px;
  background:
    linear-gradient(180deg, rgba(255, 253, 249, .6), rgba(244, 241, 234, .95));
}
.form-inner {
  width: 100%;
  max-width: 340px;
  animation: rise .6s .18s ease both;
}
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
.form-submit { margin-bottom: 8px; }
.submit-btn {
  width: 100%;
  height: 44px;
  letter-spacing: .28em;
  font-size: 14px;
}
.to-register { margin-top: 6px; font-size: 12.5px; color: var(--muted); }
.to-register a { color: var(--amber); text-decoration: none; font-weight: 600; }
.to-register a:hover { text-decoration: underline; }
.form-note {
  margin-top: 26px;
  padding-top: 14px;
  border-top: 1px dashed var(--line);
  color: #8b949d;
  font-size: 11.5px;
  line-height: 1.7;
}

@keyframes rise {
  from { opacity: 0; transform: translateY(14px); }
  to { opacity: 1; transform: translateY(0); }
}

@media (max-width: 900px) {
  .login-shell { grid-template-columns: 1fr; }
  .brand-panel { padding: 30px 24px; gap: 22px; min-height: auto; }
  .brand-panel::after { width: 100%; height: 3px; bottom: 0; top: auto; background: linear-gradient(90deg, var(--amber), transparent); }
  .brand-wordmark { font-size: 44px; }
  .brand-line { font-size: 12px; }
  .brand-list { display: none; }
  .form-panel { padding: 26px 20px 40px; }
  .form-inner { max-width: 380px; }
}
</style>
