import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Backend FastAPI khi chạy `npm run dev`. Build production không dùng giá trị này:
// UI được FastAPI phục vụ cùng origin nên mọi request đi thẳng tới server đó.
const backend = process.env.CALLBOT_API_URL ?? "http://localhost:8000";

// Route backend mà UI gọi hoặc link tới (Swagger), để `npm run dev` chạy như production.
// "/livekit/" có "/" cuối: "/livekit" là trang UI, chỉ "/livekit/token" thuộc backend.
const backendPaths = [
  "/docs",
  "/openapi.json",
  "/v1",
  "/demo-api",
  "/livekit/",
  "/audio",
  "/health",
  "/ready",
  "/internal",
];

export default defineConfig({
  // FastAPI phục vụ bản build ở gốc domain (transports/http/ui.py).
  base: "/",
  plugins: [react()],
  build: {
    // Chunk lớn nhất là LiveKitPage (~530 kB, gần hết là livekit-client) và chỉ tải khi mở
    // trang đó (route lazy). Ngưỡng mặc định 500 kB sẽ cảnh báo mãi cho một điều đã biết.
    chunkSizeWarningLimit: 600,
  },
  server: {
    proxy: Object.fromEntries(backendPaths.map((path) => [path, backend])),
  },
  test: {
    // e2e/ là Playwright (npm run e2e), không chạy trong Vitest.
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    restoreMocks: true,
  },
});
