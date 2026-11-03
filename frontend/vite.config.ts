import tailwindcss from '@tailwindcss/vite';
import react from '@vitejs/plugin-react';
import {defineConfig} from 'vite';

export default defineConfig(() => {
  return {
    plugins: [react(), tailwindcss()],
    server: {
      // HMR is disabled in AI Studio via DISABLE_HMR env var.
      // Do not modify this setting; file watching is disabled to prevent flickering during agent edits.
      hmr: process.env.DISABLE_HMR !== 'true',
      // Disable file watching when DISABLE_HMR is true to save CPU during agent edits.
      watch: process.env.DISABLE_HMR === 'true' ? null : {},
      // In dev, forward API/auth/static calls to FastAPI.
      proxy: {
        '/api': {
          target: process.env.FASTAPI_URL || 'http://localhost:8000',
          changeOrigin: true,
        },
        '/auth': {
          target: process.env.FASTAPI_URL || 'http://localhost:8000',
          changeOrigin: true,
        },
        '/health': {
          target: process.env.FASTAPI_URL || 'http://localhost:8000',
          changeOrigin: true,
        },
        // Static assets (logo, favicon) are served by FastAPI.
        '/static': {
          target: process.env.FASTAPI_URL || 'http://localhost:8000',
          changeOrigin: true,
        },
      },
    },
  };
});
