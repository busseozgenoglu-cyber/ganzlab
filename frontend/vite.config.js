import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// Geliştirmede /api ve /files istekleri FastAPI arka ucuna (8000) yönlendirilir.
const proxy = {
  '/api': 'http://localhost:8000',
  '/files': 'http://localhost:8000',
}

export default defineConfig({
  plugins: [react()],
  server: { port: 5173, proxy },
  preview: { port: 4173, proxy },
})
