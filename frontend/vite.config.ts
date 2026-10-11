import vue from "@vitejs/plugin-vue";
import { defineConfig } from "vite";

// 开发时代理到本机面板后端；构建产物 dist/ 由后端静态挂载。
export default defineConfig({
  base: "/panel/",
  plugins: [vue()],
  server: {
    proxy: {
      "/api": {
        target: "http://127.0.0.1:6006",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
  },
});
