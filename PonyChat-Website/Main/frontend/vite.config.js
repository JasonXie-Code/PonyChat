import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'
import { fileURLToPath, URL } from 'node:url'

/** Cursor / VS Code Simple Browser：去掉 /@vite/client，避免其 WebSocket 初始化失败导致整页白屏 */
const simpleBrowser = process.env.VITE_SIMPLE_BROWSER === '1'
const hmrEnabled = !simpleBrowser && process.env.VITE_HMR !== '0'

function stripViteClientPlugin() {
  return {
    name: 'ponychat-strip-vite-client',
    enforce: 'post',
    transformIndexHtml(html) {
      if (!simpleBrowser) return html
      return html.replace(/<script\s+type="module"\s+src="\/@vite\/client"\s*><\/script>\s*/i, '')
    },
  }
}

export default defineConfig({
  plugins: [
    vue({
      template: {
        compilerOptions: {
          isCustomElement: (tag) => tag === 'ion-icon',
        },
      },
    }),
    stripViteClientPlugin(),
  ],
  base: '/',
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./src', import.meta.url)),
    },
  },
  server: {
    // 显式绑定 IPv4：避免仅监听 [::1] 时，部分环境把 localhost 解析到 127.0.0.1 导致「无效响应」
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    hmr: hmrEnabled
      ? { overlay: false, host: '127.0.0.1', port: 5173, protocol: 'ws' }
      : false,
    proxy: {
      '/api': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:5000', ws: true },
      '/download': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/logo': { target: 'http://127.0.0.1:5000', changeOrigin: true },
      '/assets': { target: 'http://127.0.0.1:5000', changeOrigin: true },
    },
  },
  preview: {
    host: '127.0.0.1',
    port: 4173,
    strictPort: true,
    // Preview must serve built /assets and /logo itself, not inherit dev proxies.
    proxy: {
      '/api': { target: 'https://www.ponychat.org', changeOrigin: true },
      '/download': { target: 'https://www.ponychat.org', changeOrigin: true },
    },
  },
})
