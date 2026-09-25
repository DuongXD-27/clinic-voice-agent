import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../test/server";
import { checkServices } from "./api";

describe("checkServices", () => {
  it("báo up khi /health và /ready đều trả 200", async () => {
    const snapshot = await checkServices();

    expect(snapshot.health).toEqual({ state: "up" });
    expect(snapshot.readiness).toEqual({ state: "up" });
    expect(snapshot.checkedAt).toBeInstanceOf(Date);
  });

  it("giữ mã lỗi /ready khi session store không sẵn sàng", async () => {
    server.use(
      http.get("/ready", () =>
        HttpResponse.json(
          { status: "unavailable", code: "SESSION_STORE_UNAVAILABLE" },
          { status: 503 },
        ),
      ),
    );

    const snapshot = await checkServices();

    expect(snapshot.health).toEqual({ state: "up" });
    expect(snapshot.readiness).toEqual({
      state: "down",
      code: "SESSION_STORE_UNAVAILABLE",
      message: "HTTP 503",
    });
  });

  it("báo down với NETWORK_ERROR khi không tới được server", async () => {
    server.use(
      http.get("/health", () => HttpResponse.error()),
      http.get("/ready", () => HttpResponse.error()),
    );

    const snapshot = await checkServices();

    expect(snapshot.health).toMatchObject({ state: "down", code: "NETWORK_ERROR" });
    expect(snapshot.readiness).toMatchObject({ state: "down", code: "NETWORK_ERROR" });
  });
});
