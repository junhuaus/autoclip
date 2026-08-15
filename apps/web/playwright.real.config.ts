import { defineConfig } from "@playwright/test";

const baseURL = process.env.LIVECLIP_E2E_BASE_URL;
const outputDir = process.env.LIVECLIP_E2E_OUTPUT_DIR;
const explicitChrome = process.env.LIVECLIP_CHROME_EXECUTABLE;

if (!baseURL || !outputDir) {
  throw new Error("real browser E2E must be started through scripts/run_real_browser_e2e.sh");
}

export default defineConfig({
  testDir: "./e2e-real",
  outputDir,
  preserveOutput: "always",
  timeout: 180_000,
  expect: { timeout: 120_000 },
  fullyParallel: false,
  workers: 1,
  reporter: "list",
  use: {
    baseURL,
    ...(explicitChrome ? { executablePath: explicitChrome } : { channel: "chrome" }),
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
  },
});
