import { resolve } from 'node:path'
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Two pages, one build, served by Django: the business portal (index.html,
// business.getlovelly.cloud or /business/) and the staff dashboard
// (staff.html, /staff/). Assets from /static/portal/.
// `npm run dev` proxies the API to the local Django server.
export default defineConfig(({ command }) => ({
  plugins: [react()],
  base: command === 'build' ? '/static/portal/' : '/business/',
  server: { port: 5174, proxy: { '/api': 'http://127.0.0.1:8000' } },
  build: {
    outDir: 'dist', emptyOutDir: true, sourcemap: false,
    rollupOptions: { input: { main: resolve(__dirname, 'index.html'), staff: resolve(__dirname, 'staff.html') } },
  },
}))
