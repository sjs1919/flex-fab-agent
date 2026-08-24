import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发代理到本地 demo API（FastAPI :8000）；构建产物零后端依赖（纯静态）
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/dashboard': 'http://127.0.0.1:8000',
      '/kpi': 'http://127.0.0.1:8000',
    },
  },
})
