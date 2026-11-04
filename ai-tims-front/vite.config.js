import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发代理指向 VM 本机网关（dev server 与网关同机，默认 localhost:8080；可用 VITE_GATEWAY 覆盖）
const GATEWAY = process.env.VITE_GATEWAY || 'http://localhost:8080'

export default defineConfig({
  plugins: [vue()],
  server: {
    host: true,
    port: 5173,
    proxy: {
      '/api': { target: GATEWAY, changeOrigin: true },
      '/ws': { target: GATEWAY.replace('http', 'ws'), ws: true }
    }
  }
})
