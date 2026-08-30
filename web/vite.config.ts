import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发代理到本地 flex-fab-agent API（FastAPI :8000）；构建产物零后端依赖（纯静态）
// 默认 127.0.0.1:8000（前后端同机 Windows）；vite 跑在 WSL 而 API 在 Windows 时
// 用 API_PROXY=http://<windows-host-ip>:8000 覆盖（联调用，不提交固定 IP）
const apiTarget = process.env.API_PROXY || 'http://127.0.0.1:8000'

export default defineConfig(({ command }) => ({
  plugins: [vue()],
  // 生产构建部署在 https://dev.wzhlink.cn/flex-fab-agent/ 子路径：
  // build 产物资源统一带 /flex-fab-agent/ 前缀；dev（command=serve）保持根路径，不影响本地开发
  base: command === 'build' ? '/flex-fab-agent/' : '/',
  server: {
    port: 5173,
    proxy: {
      '/dashboard': apiTarget,
      '/kpi': apiTarget,
      '/debug': apiTarget,
      '/config': apiTarget,
      '/ask': apiTarget,
      '/schedule': apiTarget,
    },
  },
}))
