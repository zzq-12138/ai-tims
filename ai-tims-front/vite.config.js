import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发代理指向 VM 网关（tomcat9 已停服，网关已回到 8080）
const GATEWAY = process.env.VITE_GATEWAY || 'http://192.168.40.10:8080'

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
