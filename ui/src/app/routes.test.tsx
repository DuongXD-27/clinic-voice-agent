import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { createMemoryRouter, RouterProvider } from "react-router";
import { beforeEach, describe, expect, it } from "vitest";

import { getApiKey, login, logout, rejectApiKey } from "../lib/auth";
import { server } from "../test/server";
import { routes } from "./routes";

function renderAt(path: string) {
  const router = createMemoryRouter(routes, { initialEntries: [path] });
  render(<RouterProvider router={router} />);
  return router;
}

/** Bot kiểm key như smoke test CD: key đúng → 422, sai → 401 BAD_KEY. */
function keyCheck(valid: string) {
  const seen: (string | null)[] = [];
  server.use(
    http.post("/v1/calls", ({ request }) => {
      const auth = request.headers.get("Authorization");
      seen.push(auth);
      return auth === `Bearer ${valid}`
        ? HttpResponse.json({ detail: [{ msg: "Field required" }] }, { status: 422 })
        : HttpResponse.json(
            { detail: { code: "BAD_KEY", message: "Invalid bearer token." } },
            { status: 401 },
          );
    }),
    http.get("/demo-api/clinic-fixtures", () =>
      HttpResponse.json({ source: "sim", appointments: [], phones: [] }),
    ),
  );
  return seen;
}

describe("đăng nhập", () => {
  beforeEach(() => {
    logout();
  });

  it("chưa đăng nhập: mở link nào cũng về /login, đăng nhập xong quay lại đúng trang", async () => {
    const seen = keyCheck("sk_good");
    const router = renderAt("/call?x=1");

    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập" })).toBeInTheDocument();
    expect(router.state.location.search).toBe("?next=%2Fcall%3Fx%3D1");
    expect(screen.queryByRole("navigation", { name: "Điều hướng chính" })).not.toBeInTheDocument();

    await userEvent.type(screen.getByLabelText("API key"), "sk_bad");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));
    expect(await screen.findByText("API key không đúng.")).toBeInTheDocument();
    expect(getApiKey()).toBeNull();

    await userEvent.clear(screen.getByLabelText("API key"));
    await userEvent.type(screen.getByLabelText("API key"), " sk_good ");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(
      await screen.findByRole("heading", { level: 1, name: "Cuộc gọi từng lượt (Text/Audio)" }),
    ).toBeInTheDocument();
    expect(router.state.location.pathname + router.state.location.search).toBe("/call?x=1");
    expect(getApiKey()).toBe("sk_good");
    expect(window.sessionStorage.getItem("callbotApiKey")).toBe("sk_good");
    expect(seen).toEqual(["Bearer sk_bad", "Bearer sk_good"]);
  });

  it("bot tắt auth: để trống key vẫn vào được", async () => {
    server.use(http.post("/v1/calls", () => HttpResponse.json({ detail: [] }, { status: 422 })));
    renderAt("/login");

    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByRole("heading", { level: 1, name: "Tổng quan" })).toBeInTheDocument();
    expect(getApiKey()).toBe("");
  });

  it("không tới được bot: báo lỗi, không đăng nhập", async () => {
    server.use(http.post("/v1/calls", () => new HttpResponse(null, { status: 502 })));
    renderAt("/login");

    await userEvent.type(screen.getByLabelText("API key"), "sk_x");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));

    expect(await screen.findByText("Không kết nối được tới bot (HTTP 502).")).toBeInTheDocument();
    expect(getApiKey()).toBeNull();
  });

  it("chỉ quay về trang trong app, không theo next ra ngoài", async () => {
    keyCheck("sk_good");
    const router = renderAt("/login?next=%2F%2Fevil.example");

    await userEvent.type(screen.getByLabelText("API key"), "sk_good");
    await userEvent.click(screen.getByRole("button", { name: "Đăng nhập" }));

    await screen.findByRole("heading", { level: 1, name: "Tổng quan" });
    expect(router.state.location.pathname).toBe("/");
  });

  it("đăng xuất về trang đăng nhập; key bị bot từ chối thì báo lý do", async () => {
    login("sk_good");
    renderAt("/");
    await screen.findByRole("heading", { level: 1, name: "Tổng quan" });

    await userEvent.click(screen.getByRole("button", { name: "Đăng xuất" }));
    expect(screen.getByRole("heading", { level: 1, name: "Đăng nhập" })).toBeInTheDocument();
    expect(screen.queryByText(/không còn hợp lệ/)).not.toBeInTheDocument();
    expect(window.sessionStorage.getItem("callbotApiKey")).toBeNull();

    login("sk_old");
    act(() => {
      rejectApiKey();
    });
    expect(screen.getByText("API key không còn hợp lệ. Đăng nhập lại.")).toBeInTheDocument();
  });
});

describe("app", () => {
  beforeEach(() => {
    login("");
  });

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

  it("thanh bên thu gọn / mở rộng và nhớ lựa chọn", async () => {
    window.localStorage.removeItem("callbotSidebarCollapsed");
    renderAt("/");
    const sidebar = screen.getByRole("complementary", { name: "Thanh bên" });

    await userEvent.click(screen.getByRole("button", { name: "Thu gọn thanh bên" }));

    // Chỉ còn icon nhưng link vẫn giữ tên truy cập, rê chuột thấy tên.
    expect(sidebar.className).toMatch(/collapsed/);
    const nav = within(screen.getByRole("navigation", { name: "Điều hướng chính" }));
    expect(nav.getByRole("link", { name: "Gọi từng lượt" })).toHaveAttribute(
      "title",
      "Gọi từng lượt",
    );
    expect(window.localStorage.getItem("callbotSidebarCollapsed")).toBe("1");

    await userEvent.click(screen.getByRole("button", { name: "Mở rộng thanh bên" }));
    expect(sidebar.className).not.toMatch(/collapsed/);
    expect(window.localStorage.getItem("callbotSidebarCollapsed")).toBe("0");
  });

  it("màn hẹp: nút menu mở ngăn kéo; chọn trang, Esc hoặc nút đóng thì đóng", async () => {
    server.use(
      http.get("/demo-api/clinic-fixtures", () =>
        HttpResponse.json({ source: "sim", appointments: [], phones: [] }),
      ),
    );
    renderAt("/");
    const sidebar = screen.getByRole("complementary", { name: "Thanh bên" });
    const menu = screen.getByRole("button", { name: "Mở menu" });

    await userEvent.click(menu);
    expect(menu).toHaveAttribute("aria-expanded", "true");
    expect(sidebar.className).toMatch(/open/);
    expect(screen.getByRole("button", { name: "Đóng menu" })).toHaveFocus();

    await userEvent.keyboard("{Escape}");
    expect(menu).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(menu);
    await userEvent.click(screen.getByRole("button", { name: "Đóng menu" }));
    expect(menu).toHaveAttribute("aria-expanded", "false");

    await userEvent.click(menu);
    const nav = within(screen.getByRole("navigation", { name: "Điều hướng chính" }));
    await userEvent.click(nav.getByRole("link", { name: "Gọi từng lượt" }));
    expect(menu).toHaveAttribute("aria-expanded", "false");
    expect(
      screen.getByRole("heading", { level: 1, name: "Cuộc gọi từng lượt (Text/Audio)" }),
    ).toBeInTheDocument();
  });

  it("đường dẫn lạ hiện trang 404 trong layout", () => {
    renderAt("/khong-co");

    expect(screen.getByRole("heading", { name: "Không tìm thấy trang" })).toBeInTheDocument();
    expect(screen.getByRole("navigation", { name: "Điều hướng chính" })).toBeInTheDocument();
  });
});
