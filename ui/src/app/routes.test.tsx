import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router";
import { describe, expect, it } from "vitest";

import { server } from "../test/server";
import { routes } from "./routes";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  return render(<RouterProvider router={router} />);
}

describe("app", () => {
  it("trang tổng quan liệt kê đủ các công cụ, đều là route trong app", async () => {
    renderAt("/");

    expect(screen.getByRole("heading", { level: 1, name: "Tổng quan" })).toBeInTheDocument();
    const tools = within(screen.getByRole("region", { name: "Công cụ" }));
    expect(tools.getByRole("link", { name: /Gọi từng lượt/ })).toHaveAttribute("href", "/call");
    expect(tools.getByRole("link", { name: /Gọi trực tiếp/ })).toHaveAttribute("href", "/livekit");
    expect(tools.getByRole("link", { name: /Thử STT/ })).toHaveAttribute("href", "/stt");
    expect(tools.getByRole("link", { name: /Observability/ })).toHaveAttribute(
      "href",
      "/observability",
    );
    expect(await screen.findByText("Hệ thống hoạt động")).toBeInTheDocument();
  });

  it("đánh dấu mục điều hướng đang mở", () => {
    renderAt("/");

    const nav = within(screen.getByRole("navigation", { name: "Điều hướng chính" }));
    expect(nav.getByRole("link", { name: "Tổng quan" })).toHaveAttribute("aria-current", "page");
  });

  it("hiện mã lỗi khi session store không sẵn sàng", async () => {
    server.use(
      http.get("/ready", () =>
        HttpResponse.json(
          { status: "unavailable", code: "SESSION_STORE_UNAVAILABLE" },
          { status: 503 },
        ),
      ),
    );
    renderAt("/");

    expect(await screen.findByText("SESSION_STORE_UNAVAILABLE")).toBeInTheDocument();
    expect(screen.getByText("Session store lỗi")).toBeInTheDocument();
  });

  it("nút kiểm tra lại gọi lại backend", async () => {
    let calls = 0;
    server.use(
      http.get("/health", () => {
        calls += 1;
        return HttpResponse.json({ status: "ok" });
      }),
    );
    renderAt("/");
    await screen.findByText("Hệ thống hoạt động");

    await userEvent.click(screen.getByRole("button", { name: "Kiểm tra lại" }));

    await screen.findByText("Hệ thống hoạt động");
    expect(calls).toBeGreaterThanOrEqual(2);
  });

  it("mở trang cuộc gọi thử từ menu", async () => {
    server.use(
      http.get("/demo-api/clinic-fixtures", () =>
        HttpResponse.json({ source: "sim", appointments: [], phones: [] }),
      ),
    );
    renderAt("/");

    const nav = within(screen.getByRole("navigation", { name: "Điều hướng chính" }));
    await userEvent.click(nav.getByRole("link", { name: "Gọi từng lượt" }));

    expect(
      screen.getByRole("heading", { level: 1, name: "Cuộc gọi từng lượt (Text/Audio)" }),
    ).toBeInTheDocument();
    expect(nav.getByRole("link", { name: "Gọi từng lượt" })).toHaveAttribute(
      "aria-current",
      "page",
    );
    await screen.findByText(/Nguồn: clinic giả/);
  });

  it("trang LiveKit tải lazy khi mở", async () => {
    renderAt("/livekit");

    expect(
      await screen.findByRole("heading", { level: 1, name: "Cuộc gọi trực tiếp" }),
    ).toBeInTheDocument();
  });

  it("đường dẫn lạ hiện trang 404 trong layout", () => {
    renderAt("/khong-co");

    expect(screen.getByRole("heading", { name: "Không tìm thấy trang" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeInTheDocument();
  });
});
