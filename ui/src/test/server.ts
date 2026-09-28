import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";

/** Backend giả mặc định: mọi thứ khỏe. Test cần lỗi thì `server.use(...)` đè lên. */
export const handlers = [
  http.get("/health", () => HttpResponse.json({ status: "ok" })),
  http.get("/ready", () => HttpResponse.json({ status: "ready" })),
];

export const server = setupServer(...handlers);
