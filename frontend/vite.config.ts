import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  cacheDir: 'node_modules/.vite-rus-ukr',
  server: {
    host: '127.0.0.1',
    port: 5175,
    strictPort: true,
    open: false,
    clearScreen: false,
  },
});
