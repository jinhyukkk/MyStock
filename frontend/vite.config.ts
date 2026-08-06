import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Lightning CSS가 backdrop-filter를 webkit 접두사로만 남기지 않도록 모던 타깃 고정
  build: { cssTarget: 'chrome110' },
  server: { proxy: { '/api': 'http://localhost:8000' } },
})
