import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import { routes } from "../../../app/routes";
import { login } from "../../../lib/auth";
import { server } from "../../../test/server";
import { callDetail, overview, quality, turn } from "../test/fixtures";

const BASE = "/internal/observability";

/** Backend observability giả; ghi lại query của từng request để kiểm tham số. */
function backend() {
  const seen: Record<string, URLSearchParams[]> = {};
  const record = (name: string, request: Request) => {
    (seen[name] ??= []).push(new URL(request.url).searchParams);
  };
  server.use(
    http.get(`${BASE}/overview`, ({ request }) => {
      record("overview", request);
      return HttpResponse.json(overview);
    }),
    http.get(`${BASE}/errors`, ({ request }) => {
      record("errors", request);
      return HttpResponse.json({
        items: [
          {
            component: "STT",
            provider: "zipformer",
            model: "gipformer1.5",
            error_code: "ASR_TIMEOUT",
            count: 1,
          },
          { component: "TTS", provider: "vbee", model: "hn", error_code: "TTS_HTTP_500", count: 3 },
        ],
        limit: 25,
      });
    }),
    http.get(`${BASE}/slow-turns`, ({ request }) => {
      record("slow", request);
      return HttpResponse.json({
        items: [
          {
            call_key: "call_abc",
            turn: 2,
            trace_id: "trace_123",
            start_time: "2026-09-24T10:05:00Z",
            duration_ms: 2400,
            stt_ms: 800,
            core_ms: 300,
            tts_ms: 1200,
            status: "OK",
            error_codes: [],
          },
        ],
        limit: 25,
        offset: 0,
      });
    }),
    http.get(`${BASE}/quality`, ({ request }) => {
      record("quality", request);
      const component = new URL(request.url).searchParams.get("component") ?? "STT";
      return HttpResponse.json({ ...quality, component });
    }),
    http.get(`${BASE}/calls/:callKey`, ({ request }) => {
      record("call", request);
      return HttpResponse.json(callDetail);
    }),
    http.get(`${BASE}/turns/:traceId`, ({ request }) => {
      record("turn", request);
      return HttpResponse.json(turn);
    }),
  );
  return seen;
}

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

// Mọi trang trong app cần đăng nhập; bot tắt auth thì key rỗng.
beforeEach(() => {
  login("");
});

describe("Observability", () => {
  it("tổng quan: 7 thẻ KPI; chọn STT mở biểu đồ, provider, mã lỗi đúng thành phần", async () => {
    const seen = backend();
    const router = renderAt("/observability");

    expect(await screen.findByText(/42 lượt · 180 bản ghi trace/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { pressed: false })).toHaveLength(7);
    expect(seen.overview?.[0]?.get("slow_threshold_ms")).toBe("2000");

    await userEvent.click(screen.getByRole("button", { name: /^STT/ }));

    expect(router.state.location.search).toContain("metric=stt");
    expect(screen.getByRole("heading", { name: "Thời lượng observation STT" })).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /Biểu đồ p95/ })).toBeInTheDocument();
    expect(
      screen.getByRole("table", { name: "Hiệu năng theo provider và model" }),
    ).toHaveTextContent("zipformer");
    const errors = await screen.findByRole("table", { name: "Mã lỗi thường gặp" });
    expect(errors).toHaveTextContent("ASR_TIMEOUT");
    expect(errors).not.toHaveTextContent("TTS_HTTP_500");

    await userEvent.click(screen.getByRole("button", { name: "Đóng" }));
    expect(router.state.location.search).not.toContain("metric");
  });

  it("từ lượt chậm mở chi tiết lượt rồi quay về cuộc gọi", async () => {
    const seen = backend();
    renderAt("/observability?range=1&metric=slow_turn");

    await userEvent.click(await screen.findByRole("link", { name: "Chi tiết →" }));

    expect(await screen.findByRole("heading", { name: "Các stage của lượt" })).toBeInTheDocument();
    expect(screen.getAllByText("SLOT_TAKEN").length).toBeGreaterThan(0);
    expect(screen.getByText("CLINIC", { selector: "article strong" })).toBeInTheDocument();
    // Khoảng 1 giờ được giữ khi chuyển trang.
    const window = seen.turn?.[0];
    expect(Date.parse(window?.get("end") ?? "") - Date.parse(window?.get("start") ?? "")).toBe(
      3_600_000,
    );

    await userEvent.click(screen.getByRole("link", { name: "Cuộc gọi" }));

    const executions = await screen.findByRole("table", { name: "Các lượt của cuộc gọi" });
    expect(within(executions).getAllByRole("row")).toHaveLength(3);
    expect(within(executions).getByText("Chạy lại")).toBeInTheDocument();
  });

  it("chất lượng: tóm tắt, lọc theo loại vấn đề, đổi module gọi lại API", async () => {
    const seen = backend();
    renderAt("/observability/quality");

    expect(await screen.findByText("10%")).toBeInTheDocument();
    const examples = screen.getByRole("table", { name: "Lượt bị ảnh hưởng" });
    expect(within(examples).getAllByRole("row")).toHaveLength(3);

    await userEvent.click(screen.getByRole("button", { name: /^Độ tin cậy thấp: 5%/ }));
    expect(screen.getByRole("heading", { name: "Ví dụ: Độ tin cậy thấp" })).toBeInTheDocument();
    expect(
      within(screen.getByRole("table", { name: "Lượt bị ảnh hưởng" })).getAllByRole("row"),
    ).toHaveLength(2);

    await userEvent.click(screen.getByRole("radio", { name: "TTS" }));
    await screen.findByText(/có ít nhất một vấn đề TTS/);
    expect(seen.quality?.at(-1)?.get("component")).toBe("TTS");
  });

  it("API chưa bật: hướng dẫn cách bật thay vì lỗi chung chung", async () => {
    server.use(
      http.get(`${BASE}/overview`, () =>
        HttpResponse.json({ detail: "Not Found" }, { status: 404 }),
      ),
    );
    renderAt("/observability");

    expect(await screen.findByRole("alert")).toHaveTextContent("OBSERVABILITY_API_ENABLED=true");
  });

  it("đổi khoảng thời gian tải lại với khoảng mới", async () => {
    const seen = backend();
    const router = renderAt("/observability");
    await screen.findByText(/180 bản ghi trace/);

    await userEvent.click(screen.getByRole("radio", { name: "7 ngày" }));
    await screen.findByText(/180 bản ghi trace/);

    const last = seen.overview?.at(-1);
    expect(router.state.location.search).toContain("range=168");
    expect(Date.parse(last?.get("end") ?? "") - Date.parse(last?.get("start") ?? "")).toBe(
      168 * 3_600_000,
    );
  });
});
