import { fileURLToPath } from "node:url";
import { defineConfig, devices } from "@playwright/test";

const here = fileURLToPath(new URL(".", import.meta.url));

/**
 * 端對端煙霧測試：對 `docker compose up -d --build` 起來的完整系統執行。
 * 預設網址為 http://localhost:8080；8080 被占用而改用其他連接埠時，以 E2E_BASE_URL 指定。
 * 每個測試使用全新的瀏覽器 context，因此各自取得新的 session 與工作區。
 */
export default defineConfig({
  testDir: here,
  testMatch: "**/*.spec.ts",
  outputDir: fileURLToPath(new URL("../test-results", import.meta.url)),
  timeout: 90_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8080",
    locale: "zh-TW",
    timezoneId: "Asia/Taipei",
    acceptDownloads: true,
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
