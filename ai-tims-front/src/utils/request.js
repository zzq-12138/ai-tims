import axios from 'axios'
import { useAuthStore } from '../stores/auth'
import router from '../router'

const request = axios.create({ timeout: 15000 })

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
    return Promise.reject(err)
  }
)

export default request
