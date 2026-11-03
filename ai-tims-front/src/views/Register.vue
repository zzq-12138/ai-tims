<template>
  <div class="register-wrap">
    <el-card class="register-card">
      <h2 class="title">注册 AI-TIMS 账号</h2>
      <el-form ref="formRef" :model="form" :rules="rules" label-position="top" @keyup.enter="onRegister">
        <el-form-item prop="username" label="用户名">
          <el-input v-model="form.username" placeholder="3-32 位字母、数字或下划线" />
        </el-form-item>
        <el-form-item prop="nickname" label="姓名">
          <el-input v-model="form.nickname" placeholder="真实姓名或昵称" />
        </el-form-item>
        <el-form-item prop="phone" label="手机号">
          <el-input v-model="form.phone" placeholder="11 位大陆手机号" maxlength="11" />
        </el-form-item>
        <el-form-item prop="email" label="邮箱">
          <el-input v-model="form.email" placeholder="用于接收验证码">
            <template #append>
              <el-button :disabled="countdown > 0 || !emailValid" :loading="sending" @click="onSendCode">
                {{ countdown > 0 ? `${countdown}s 后重发` : '获取验证码' }}
              </el-button>
            </template>
          </el-input>
        </el-form-item>
        <el-form-item prop="code" label="邮箱验证码">
          <el-input v-model="form.code" placeholder="6 位数字，5 分钟内有效" maxlength="6" />
        </el-form-item>
        <el-form-item prop="password" label="密码">
          <el-input v-model="form.password" type="password" show-password placeholder="≥8 位，含大小写字母、数字、特殊字符" />
          <el-progress
            :percentage="strength.percent"
            :status="strength.percent >= 100 ? 'success' : 'warning'"
            :stroke-width="6"
            style="width: 100%; margin-top: 6px"
          />
          <div class="pwd-rules">
            <span :class="{ ok: strength.rules.len }">8 位以上</span>
            <span :class="{ ok: strength.rules.upper }">大写字母</span>
            <span :class="{ ok: strength.rules.lower }">小写字母</span>
            <span :class="{ ok: strength.rules.digit }">数字</span>
            <span :class="{ ok: strength.rules.special }">特殊字符</span>
          </div>
        </el-form-item>
        <el-form-item prop="confirmPassword" label="确认密码">
          <el-input v-model="form.confirmPassword" type="password" show-password placeholder="再次输入密码" />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" style="width: 100%" :loading="loading" @click="onRegister"> 注 册 </el-button>
        </el-form-item>
        <div class="to-login">已有账号？<router-link to="/login">去登录</router-link></div>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { computed, reactive, ref, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { register, sendCode } from '../api/auth'

const router = useRouter()
const formRef = ref(null)
const loading = ref(false)
const sending = ref(false)
const countdown = ref(0)
let timer = null

const form = reactive({
  username: '', nickname: '', phone: '', email: '', code: '', password: '', confirmPassword: ''
})

const PHONE_RE = /^1[3-9]\d{9}$/
const EMAIL_RE = /^[\w.+-]+@[\w-]+(\.[\w-]+)+$/
const PWD_RE = /^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)(?=.*[^0-9a-zA-Z]).{8,64}$/

const rules = {
  username: [
    { required: true, message: '请输入用户名', trigger: 'blur' },
    { pattern: /^[a-zA-Z0-9_]{3,32}$/, message: '3-32 位字母、数字或下划线', trigger: 'blur' }
  ],
  nickname: [{ required: true, message: '请输入姓名', trigger: 'blur' }],
  phone: [
    { required: true, message: '请输入手机号', trigger: 'blur' },
    { pattern: PHONE_RE, message: '手机号格式不正确', trigger: 'blur' }
  ],
  email: [
    { required: true, message: '请输入邮箱', trigger: 'blur' },
    { pattern: EMAIL_RE, message: '邮箱格式不正确', trigger: 'blur' }
  ],
  code: [
    { required: true, message: '请输入验证码', trigger: 'blur' },
    { pattern: /^\d{6}$/, message: '验证码为 6 位数字', trigger: 'blur' }
  ],
  password: [
    { required: true, message: '请输入密码', trigger: 'blur' },
    { pattern: PWD_RE, message: '≥8 位，须同时含大写、小写、数字、特殊字符', trigger: 'blur' }
  ],
  confirmPassword: [
    { required: true, message: '请再次输入密码', trigger: 'blur' },
    {
      validator: (_, v, cb) => (v === form.password ? cb() : cb(new Error('两次输入的密码不一致'))),
      trigger: 'blur'
    }
  ]
}

const emailValid = computed(() => EMAIL_RE.test(form.email))
const rulesState = computed(() => ({
  len: form.password.length >= 8,
  upper: /[A-Z]/.test(form.password),
  lower: /[a-z]/.test(form.password),
  digit: /\d/.test(form.password),
  special: /[^0-9a-zA-Z]/.test(form.password)
}))
const strength = computed(() => {
  const r = rulesState.value
  const hit = Object.values(r).filter(Boolean).length
  return { percent: hit * 20, rules: r }
})

function onSendCode() {
  if (!emailValid.value) {
    ElMessage.warning('请先输入正确的邮箱')
    return
  }
  sending.value = true
  sendCode(form.email)
    .then(() => {
      ElMessage.success('验证码已发送（开发模式可在服务日志或调试接口查看）')
      countdown.value = 60
      timer = setInterval(() => {
        countdown.value--
        if (countdown.value <= 0) clearInterval(timer)
      }, 1000)
    })
    .catch((e) => ElMessage.error(e.message || '发送失败'))
    .finally(() => (sending.value = false))
}

function onRegister() {
  formRef.value.validate((valid) => {
    if (!valid) return
    loading.value = true
    const { confirmPassword, ...payload } = form
    register(payload)
      .then(() => {
        ElMessage.success('注册成功，请登录')
        router.push('/login')
      })
      .catch((e) => ElMessage.error(e.message || '注册失败'))
      .finally(() => (loading.value = false))
  })
}

onUnmounted(() => timer && clearInterval(timer))
</script>

<style scoped>
.register-wrap {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  padding: 24px 0;
  background: linear-gradient(135deg, #1f2d3d 0%, #2b4a6f 100%);
}
.register-card {
  width: 420px;
  padding: 8px 12px;
}
.title {
  text-align: center;
  margin: 8px 0 20px;
  color: #1f2d3d;
}
.pwd-rules {
  display: flex;
  gap: 10px;
  font-size: 12px;
  color: #909399;
  margin-top: 4px;
}
.pwd-rules .ok {
  color: #67c23a;
}
.to-login {
  text-align: center;
  font-size: 13px;
  color: #606266;
}
</style>
