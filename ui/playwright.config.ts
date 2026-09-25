import { defineConfig, devices } from "@playwright/test";

/**
 * E2E chạy trên backend thật đã khởi động sẵn (không để Playwright tự bật server):
 * - CI: uvicorn + Redis + CLINIC_BACKEND=sim (job `e2e` trong ci.yml).
 * - Local: `docker compose up -d` rồi `npm run e2e`.
 * Clinic giả giữ dữ liệu trong bộ nhớ: chạy lại cần restart bot (sim) để lịch về SCHEDULED.
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  // Hai kịch bản dùng chung clinic: chạy tuần tự, không retry để lỗi dữ liệu lộ ra ngay.
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:8000",
    locale: "vi-VN",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
