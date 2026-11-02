import request from '../utils/request'

export function login(username, password) {
  return request.post('/api/auth/login', { username, password })
}

export function logout() {
  return request.post('/api/auth/logout')
}

export function me() {
  return request.get('/api/auth/me')
}
