/// <reference types="vitest" />
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import path from 'node:path';

export default defineConfig({
  plugins: [react()],
  resolve: { alias: { '@': path.resolve(__dirname, './src') } },
  server: {
    port: 5174,
    proxy: {
      '/portal': { target: 'http://localhost:8443', changeOrigin: true, secure: false },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
  test: { environment: 'jsdom', globals: true },
});
