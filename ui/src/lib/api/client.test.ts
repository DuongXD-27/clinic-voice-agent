import { http, HttpResponse } from "msw";
import { describe, expect, it } from "vitest";

import { server } from "../../test/server";
import { ApiError, NETWORK_ERROR, request, resolveUrl } from "./client";

async function captureError(promise: Promise<unknown>): Promise<ApiError> {
  try {
    await promise;
  } catch (error) {
    if (error instanceof ApiError) return error;
    throw error;
  }
  throw new Error("request() lẽ ra phải lỗi");
}

describe("request", () => {
  it("trả JSON, status, header và thời gian", async () => {
    server.use(
      http.get("/thing", () =>
        HttpResponse.json({ value: 1 }, { headers: { "X-Demo-Extraction-Source": "RULE" } }),
      ),
    );

    const result = await request<{ value: number }>("/thing");

    expect(result.data).toEqual({ value: 1 });
    expect(result.status).toBe(200);
    expect(result.headers.get("X-Demo-Extraction-Source")).toBe("RULE");
    expect(result.elapsedMs).toBeGreaterThanOrEqual(0);
  });

  it("gửi JSON kèm Bearer key đã bỏ khoảng trắng", async () => {
    let seen: { auth: string | null; type: string | null; body: unknown } | undefined;
    server.use(
      http.post("/v1/calls", async ({ request: req }) => {
        seen = {
          auth: req.headers.get("Authorization"),
          type: req.headers.get("Content-Type"),
          body: await req.json(),
        };
        return HttpResponse.json({});
      }),
    );

    await request("/v1/calls", { method: "POST", json: { call_id: "c1" }, apiKey: "  sk_1 " });

    expect(seen).toEqual({
      auth: "Bearer sk_1",
      type: "application/json",
      body: { call_id: "c1" },
    });
  });

  it("không gửi Authorization khi key rỗng", async () => {
    let auth: string | null = "unset";
    server.use(
      http.get("/health", ({ request: req }) => {
        auth = req.headers.get("Authorization");
        return HttpResponse.json({});
      }),
    );

    await request("/health", { apiKey: "   " });

    expect(auth).toBeNull();
  });

  it("gửi body nguyên văn và không tự đặt Content-Type JSON", async () => {
    let type: string | null = null;
    let size = 0;
    server.use(
      http.put("/demo-api/audio/c1/1.wav", async ({ request: req }) => {
        type = req.headers.get("Content-Type");
        size = (await req.arrayBuffer()).byteLength;
        return HttpResponse.json({});
      }),
    );

    await request("/demo-api/audio/c1/1.wav", {
      method: "PUT",
      body: new Uint8Array(44),
      headers: { "Content-Type": "audio/wav" },
    });

    expect(type).toBe("audio/wav");
    expect(size).toBe(44);
  });

  it("đọc code và message từ detail của FastAPI", async () => {
    server.use(
      http.post("/v1/calls", () =>
        HttpResponse.json(
          { detail: { code: "BAD_KEY", message: "Invalid bearer token." } },
          { status: 401, headers: { "X-Demo-Error-Code": "BAD_KEY" } },
        ),
      ),
    );

    const error = await captureError(request("/v1/calls", { method: "POST", json: {} }));

    expect(error.status).toBe(401);
    expect(error.code).toBe("BAD_KEY");
    expect(error.message).toBe("Invalid bearer token.");
    expect(error.headers?.get("X-Demo-Error-Code")).toBe("BAD_KEY");
  });

  it("lấy lỗi đầu tiên của response 422", async () => {
    server.use(
      http.post("/v1/calls", () =>
        HttpResponse.json(
          { detail: [{ msg: "Field required", loc: ["body", "call_id"] }] },
          { status: 422 },
        ),
      ),
    );

    const error = await captureError(request("/v1/calls", { method: "POST", json: {} }));

    expect(error.code).toBeNull();
    expect(error.message).toBe("Field required");
  });

  it("dùng HTTP status khi body không phải JSON", async () => {
    server.use(http.get("/boom", () => new HttpResponse("Bad Gateway", { status: 502 })));

    const error = await captureError(request("/boom"));

    expect(error.status).toBe(502);
    expect(error.message).toBe("HTTP 502");
    expect(error.body).toBe("Bad Gateway");
  });

  it("báo NETWORK_ERROR khi không tới được server", async () => {
    server.use(http.get("/health", () => HttpResponse.error()));

    const error = await captureError(request("/health"));

    expect(error.status).toBe(0);
    expect(error.code).toBe(NETWORK_ERROR);
  });

  it("để lỗi huỷ request đi qua nguyên vẹn", async () => {
    const controller = new AbortController();
    controller.abort();

    await expect(request("/health", { signal: controller.signal })).rejects.toMatchObject({
      name: "AbortError",
    });
  });
});

describe("resolveUrl", () => {
  it("mặc định cùng origin với trang", () => {
    expect(resolveUrl("/health")).toBe(`${window.location.origin}/health`);
  });

  it("dùng base URL tuỳ chỉnh, có hay không có dấu / cuối", () => {
    expect(resolveUrl("/health", "https://bot.example")).toBe("https://bot.example/health");
    expect(resolveUrl("/health", "https://bot.example/")).toBe("https://bot.example/health");
  });
});
