import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { resolve } from 'path'
import { fileURLToPath } from 'url'

const __dirname = fileURLToPath(new URL('.', import.meta.url))

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      // 后端是 Python FastAPI 单体，端口 8000。
      // ⚠️ 参照项目 huajian-xinsheng 用的是 3001 —— 本项目**刻意不同**，
      //    因为那边是 Express，这边是 uvicorn。改端口只需改这两行。
      '/api': 'http://localhost:8000',
      '/uploads': 'http://localhost:8000',
    },
  },
  resolve: {
    // 对齐 huajian-xinsheng 的 8 个别名，**去掉 @admin**
    // —— 本项目没有后台管理面，留一个指向不存在目录的别名会误导人。
    alias: {
      '@': resolve(__dirname, 'src'),
      '@components': resolve(__dirname, 'src/components'),
      '@features': resolve(__dirname, 'src/features'),
      '@lib': resolve(__dirname, 'src/lib'),
      '@stores': resolve(__dirname, 'src/stores'),
      '@hooks': resolve(__dirname, 'src/hooks'),
      '@styles': resolve(__dirname, 'src/styles'),
    },
  },
})
