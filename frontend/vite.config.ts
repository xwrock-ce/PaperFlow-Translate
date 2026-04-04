import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const proxyTarget = "http://127.0.0.1:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    proxy: {
      "/app": proxyTarget,
      "/artifacts": proxyTarget,
      "/healthz": proxyTarget,
      "/engines": proxyTarget,
      "/settings": proxyTarget,
      "/translate": proxyTarget,
      "/ui": proxyTarget,
      "/requests": proxyTarget,
    },
  },
});
