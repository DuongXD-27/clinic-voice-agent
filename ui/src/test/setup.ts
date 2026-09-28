import "@testing-library/jest-dom/vitest";

import { cleanup, configure } from "@testing-library/react";
import { afterAll, afterEach, beforeAll } from "vitest";

import { server } from "./server";

// Mặc định findBy*/waitFor chờ 1 giây: chạy cả bộ song song (jsdom nặng, CI yếu), trang lazy
// như observability có thể render chậm hơn thế và test đỏ ngẫu nhiên dù code đúng.
configure({ asyncUtilTimeout: 5000 });

// Request nào không có handler là lỗi: test không bao giờ gọi mạng thật.
beforeAll(() => {
  server.listen({ onUnhandledRequest: "error" });
});
afterEach(() => {
  cleanup();
  server.resetHandlers();
});
afterAll(() => {
  server.close();
});
