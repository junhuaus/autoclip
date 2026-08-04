import { defineConfig } from "@playwright/test";

const explicitChrome = process.env.LIVECLIP_CHROME_EXECUTABLE;

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:5174",
    ...(explicitChrome ? { executablePath: explicitChrome } : { channel: "chrome" }),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  webServer: {
    command: "npm run dev -- --port 5174",
    url: "http://127.0.0.1:5174",
    reuseExistingServer: true,
    timeout: 60_000,
  },
});
