import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

function localApiTarget(): string {
  const value = process.env.LIVECLIP_VITE_API_TARGET ?? "http://127.0.0.1:8765";
  const parsed = new URL(value);
  if (
    parsed.protocol !== "http:" ||
    !["127.0.0.1", "localhost", "[::1]"].includes(parsed.hostname) ||
    parsed.username ||
    parsed.password ||
    parsed.pathname !== "/" ||
    parsed.search ||
    parsed.hash
  ) {
    throw new Error("LIVECLIP_VITE_API_TARGET must be a plain loopback HTTP origin");
  }
  return parsed.origin;
}

export default defineConfig({
  plugins: [react()],
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: localApiTarget(),
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
