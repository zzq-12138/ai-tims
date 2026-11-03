import request from '../utils/request'

export function login(username, password) {
  return request.post('/api/auth/login', { username, password })
}

export function register(payload) {
  return request.post('/api/auth/register', payload)
}

export function sendCode(email) {
  return request.post(`/api/auth/code?email=${encodeURIComponent(email)}`)
}

export function getDebugCode(email) {
  return request.get('/api/auth/debug/code', { params: { email } })
}

export function logout() {
  return request.post('/api/auth/logout')
}

export function me() {
  return request.get('/api/auth/me')
}
