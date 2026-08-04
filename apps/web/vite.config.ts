import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8765",
        changeOrigin: true,
        configure(proxy) {
          // Vite registers its own error logger after this hook. Redact the
          // query first so a signed media URL never reaches that logger when
          // the local API is unavailable.
          proxy.on("error", (_error, _request, response) => {
            if (response && "req" in response && response.req.url) {
              response.req.url = response.req.url.split("?", 1)[0];
            }
          });
        },
      },
    },
  },
  test: {
    environment: "jsdom",
    include: ["tests/**/*.test.{ts,tsx}"],
    setupFiles: "./tests/setup.ts",
    css: true,
    restoreMocks: true,
    clearMocks: true,
  },
});
