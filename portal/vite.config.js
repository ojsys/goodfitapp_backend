import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Built into dist/ and served by Django: assets from /static/portal/,
// pages from business.getlovelly.cloud (or /business/ on any host).
// `npm run dev` proxies the API to the local Django server.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/static/portal/' : '/business/',
  server: { port: 5174, proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: { outDir: 'dist', emptyOutDir: true, sourcemap: false },
}))
