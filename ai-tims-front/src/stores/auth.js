import { defineStore } from 'pinia'

const TOKEN_KEY = 'tims_token'
const USER_KEY = 'tims_user'

export const useAuthStore = defineStore('auth', {
  state: () => ({
    token: localStorage.getItem(TOKEN_KEY) || '',
    user: JSON.parse(localStorage.getItem(USER_KEY) || 'null')
  }),
  getters: {
    isLoggedIn: (s) => !!s.token
  },
  actions: {
    setToken(token) {
      this.token = token
      localStorage.setItem(TOKEN_KEY, token)
    },
    setUser(user) {
      this.user = user
      localStorage.setItem(USER_KEY, JSON.stringify(user))
    },
    clear() {
      this.token = ''
      this.user = null
      localStorage.removeItem(TOKEN_KEY)
      localStorage.removeItem(USER_KEY)
    }
  }
})
