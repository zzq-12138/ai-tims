import axios from 'axios'
import JSONBig from 'json-bigint'
import { ElMessage } from 'element-plus'
import { useAuthStore } from '../stores/auth'
import router from '../router'

// 后端雪花 ID 为 19 位 Long，超过 JS Number 安全整数（2^53-1）。
// 默认 JSON.parse 会丢精度（2117985300138262530 → 2117985300138262500），导致详情接口 404。
// 这里用 json-bigint 解析：仅超出安全范围的整数转字符串，其余数字保持 Number。
const bigJson = JSONBig({ storeAsString: true })

const request = axios.create({
  timeout: 15000,
  transformResponse: [
    (data) => {
      // blob / 文本等非 JSON 响应原样返回
      if (typeof data !== 'string' || !data) return data
      try {
        return bigJson.parse(data)
      } catch (_) {
        return data
      }
    }
  ]
})

request.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = auth.token
  }
  return config
})

request.interceptors.response.use(
  (res) => {
    const body = res.data
    if (body && typeof body === 'object' && 'code' in body) {
      if (body.code === 0) return body.data
      // 10401 未登录/凭证失效：清会话回登录页
      if (body.code === 10401) {
        const auth = useAuthStore()
        auth.clear()
        router.push('/login')
      }
      return Promise.reject(new Error(body.message || '请求失败'))
    }
    return body
  },
  (err) => {
    if (err.response && err.response.status === 401) {
      const auth = useAuthStore()
      auth.clear()
      router.push('/login')
      return Promise.reject(new Error('未登录或凭证失效'))
    }
    // 403：后端角色校验未通过（网关与接口级统一返回 10403）。给出明确提示，不跳转、不白屏。
    if (err.response && err.response.status === 403) {
      const msg = (err.response.data && err.response.data.message) || '当前账号无权访问该功能'
      ElMessage.error(msg)
      return Promise.reject(new Error(msg))
    }
    return Promise.reject(err)
  }
)

export default request
