import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
export default defineConfig({ plugins: [vue()], base: './', publicDir: '../assets', server: { port: 5173, strictPort: true } })
