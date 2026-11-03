import request from '../utils/request'

// 系统管理（M2 补 M1 用户/角色/部门 CRUD）
export function pageUsers(params) {
  return request.get('/api/system/user/page', { params })
}

export function createUser(data) {
  return request.post('/api/system/user', data)
}

export function updateUser(data) {
  return request.put('/api/system/user', data)
}

export function deleteUser(id) {
  return request.delete(`/api/system/user/${id}`)
}

export function listRoles() {
  return request.get('/api/system/role/list')
}

export function deptTree() {
  return request.get('/api/system/dept/tree')
}
