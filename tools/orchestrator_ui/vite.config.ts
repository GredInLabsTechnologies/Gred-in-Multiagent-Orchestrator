import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
    plugins: [react()],
    server: {
        proxy: {
            '/ui': 'http://127.0.0.1:9325',
            '/ops': 'http://127.0.0.1:9325',
            '/tree': 'http://127.0.0.1:9325',
            '/file': 'http://127.0.0.1:9325',
            '/search': 'http://127.0.0.1:9325',
            '/diff': 'http://127.0.0.1:9325',
            '/api': 'http://127.0.0.1:9325',
        }
    }
})
