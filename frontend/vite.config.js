import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

export default defineConfig({
  plugins: [vue()],
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url))
    }
  },
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: process.env.INVESTIGATION_PROXY_TARGET || 'http://127.0.0.1:8000',
        changeOrigin: false
      }
    }
  },
  build: {
    outDir: 'dist',
    assetsDir: 'assets',
    rollupOptions: { output: { manualChunks(id) {
      if (id.includes('/node_modules/zrender/')) return 'quant-renderer'
      if (id.includes('/node_modules/echarts/')) return 'quant-echarts'
    } } }
  }
})
