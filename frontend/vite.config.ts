import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  // Lightning CSS가 backdrop-filter를 webkit 접두사로만 남기지 않도록 모던 타깃 고정
  build: { cssTarget: 'chrome110' },
  // 백엔드 기본 포트 80 (run.sh). 다른 포트로 띄웠다면 API_ORIGIN 으로 덮어쓴다.
  server: { proxy: { '/api': process.env.API_ORIGIN ?? 'http://localhost' } },
})
