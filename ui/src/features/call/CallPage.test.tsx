import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "../../test/server";
import { CallPage } from "./CallPage";

const FIXTURES = {
  source: "sim",
  appointments: [{ appointment_id: "apt_00417", status: "SCHEDULED", display_name: "N. V. A." }],
  phones: [{ phone: "0912345600", display_name: "N. V. A." }],
};

const EXTRACTION = encodeURIComponent(
  JSON.stringify({
    transcript: "Có, tôi đến được",
    silent: false,
    fields: [{ field: "agreement", value: "AGREE", span: "đến được", provenance: "EXACT" }],
  }),
);

interface Recorded {
  start: unknown[];
  turns: unknown[];
  fixtures: number;
}

function backend(): Recorded {
  const recorded: Recorded = { start: [], turns: [], fixtures: 0 };
  server.use(
    http.get("/demo-api/clinic-fixtures", () => {
      recorded.fixtures += 1;
      return HttpResponse.json(FIXTURES);
    }),
    http.post("/v1/calls", async ({ request }) => {
      recorded.start.push(await request.json());
      return HttpResponse.json({
        call_id: "c1",
        utterance: "Xin chào, em là trợ lý ảo của Vinmec.",
        audio_url: null,
        state: "AWAITING_IDENTITY",
        turn: 0,
      });
    }),
    http.post("/v1/calls/:callId/turn", async ({ request }) => {
      const body = (await request.json()) as { turn: number };
      recorded.turns.push(body);
      return HttpResponse.json(
        {
          utterance: "Em đã xác nhận lịch khám của anh chị.",
          audio_url: null,
          state: "ENDED",
          ended: true,
          outcome: "CONFIRMED",
        },
        {
          headers: {
            "X-Demo-Extraction-Source": "RULE",
            "X-Demo-Extraction-Provenance": "EXACT",
            "X-Demo-Extraction-Fields": EXTRACTION,
          },
        },
      );
    }),
  );
  return recorded;
}

async function startCall() {
  await userEvent.click(screen.getByRole("button", { name: "Bắt đầu cuộc gọi" }));
  await screen.findByText("Xin chào, em là trợ lý ảo của Vinmec.");
}

beforeEach(() => {
  window.sessionStorage.clear();
});

describe("CallPage", () => {
  it("chạy trọn một cuộc gọi text: mở, gửi lượt, kết thúc với outcome", async () => {
    const recorded = backend();
    render(<CallPage />);
    await screen.findByText(/Nguồn: clinic giả \(local\)/);

    await startCall();
    expect(recorded.start[0]).toMatchObject({
      direction: "outbound",
      appointment_id: "apt_00417",
      caller_number: null,
      mode: "text",
      max_turns: 20,
    });
    expect(screen.getByLabelText("Call ID")).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Lời người gọi"), "Có, tôi đến được{Enter}");

    expect(await screen.findByText("Em đã xác nhận lịch khám của anh chị.")).toBeInTheDocument();
    expect(recorded.turns[0]).toEqual({
      turn: 1,
      text: "Có, tôi đến được",
      audio_url: null,
      silence_ms: 0,
    });
    // Badge outcome trong thanh trạng thái (thẻ kịch bản mẫu cũng có chữ CONFIRMED).
    expect(screen.getByText("CONFIRMED", { selector: "dd *" })).toBeInTheDocument();
    expect(screen.getByText("Cuộc gọi đã kết thúc: CONFIRMED.")).toBeInTheDocument();
    expect(screen.getByText("đến được", { selector: "mark" })).toBeInTheDocument();
    expect(screen.getByText(/Trích xuất: RULE \(EXACT\)/)).toBeInTheDocument();
    expect(screen.getByLabelText("Lời người gọi")).toBeDisabled();
    // Lịch vừa đổi trạng thái: dropdown được tải lại.
    await waitFor(() => {
      expect(recorded.fixtures).toBe(2);
    });
  });

  it("gửi lượt im lặng với silence_ms và không có text", async () => {
    const recorded = backend();
    render(<CallPage />);
    await startCall();

    await userEvent.click(screen.getByRole("button", { name: "Im lặng 2 giây" }));

    await screen.findByText("(im lặng 2 giây)");
    expect(recorded.turns[0]).toEqual({ turn: 1, text: null, audio_url: null, silence_ms: 2000 });
  });

  it("thiếu API key: báo hướng dẫn và đánh dấu ô API key", async () => {
    backend();
    server.use(
      http.post("/v1/calls", () =>
        HttpResponse.json(
          { detail: { code: "BAD_KEY", message: "Missing bearer token." } },
          { status: 401 },
        ),
      ),
    );
    render(<CallPage />);

    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu cuộc gọi" }));

    expect(await screen.findByText(/Bot yêu cầu API key/)).toBeInTheDocument();
    const apiKey = screen.getByLabelText("API key");
    expect(apiKey).toHaveAttribute("aria-invalid", "true");
    expect(apiKey).toHaveFocus();
    expect(screen.getByLabelText("Call ID")).toBeEnabled();

    await userEvent.type(apiKey, "sk_1");
    expect(apiKey).toHaveAttribute("aria-invalid", "false");
  });

  it("gửi API key đã nhập dưới dạng Bearer và nhớ trong tab", async () => {
    backend();
    let auth: string | null = null;
    server.use(
      http.post("/v1/calls", ({ request }) => {
        auth = request.headers.get("Authorization");
        return HttpResponse.json({
          call_id: "c1",
          utterance: "Xin chào, em là trợ lý ảo của Vinmec.",
          audio_url: null,
          state: "AWAITING_IDENTITY",
          turn: 0,
        });
      }),
    );
    render(<CallPage />);

    await userEvent.type(screen.getByLabelText("API key"), "sk_test");
    await userEvent.tab();
    await startCall();

    expect(auth).toBe("Bearer sk_test");
    expect(window.sessionStorage.getItem("callbotApiKey")).toBe("sk_test");
  });

  it("lượt lỗi giữ cuộc gọi mở để gửi lại, panel debug hiện response lỗi", async () => {
    backend();
    server.use(
      http.post("/v1/calls/:callId/turn", () =>
        HttpResponse.json(
          {
            detail: { code: "SESSION_STORE_UNAVAILABLE", message: "Session store không sẵn sàng" },
          },
          { status: 503 },
        ),
      ),
    );
    render(<CallPage />);
    await startCall();

    await userEvent.type(screen.getByLabelText("Lời người gọi"), "alo{Enter}");

    expect(await screen.findByText("Session store không sẵn sàng")).toBeInTheDocument();
    expect(screen.getByLabelText("Lời người gọi")).toBeEnabled();
    expect(screen.getByLabelText("Lời người gọi")).toHaveValue("alo");
    expect(screen.getByText(/RESPONSE 503/)).toBeInTheDocument();
  });

  it("chặn cấu hình sai trước khi gọi API", async () => {
    backend();
    render(<CallPage />);
    const callId = screen.getByLabelText("Call ID");

    await userEvent.clear(callId);
    await userEvent.type(callId, "c/../x");
    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu cuộc gọi" }));

    expect(await screen.findByText(/Call ID chỉ được chứa/)).toBeInTheDocument();
  });

  it("fixtures bị tắt: vẫn gọi được với lịch mặc định", async () => {
    backend();
    server.use(
      http.get("/demo-api/clinic-fixtures", () =>
        HttpResponse.json(
          { detail: { code: "CLINIC_ADMIN_DISABLED", message: "Tiện ích clinic đã tắt" } },
          { status: 404 },
        ),
      ),
    );
    render(<CallPage />);

    expect(
      await screen.findByText(/Không tải được dữ liệu clinic \(Tiện ích clinic đã tắt\)/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Appointment ID")).toHaveValue("apt_00417");
  });

  it("kịch bản mẫu: điền cấu hình inbound rồi điền câu mẫu vào ô nhập", async () => {
    const recorded = backend();
    render(<CallPage />);
    await screen.findByText(/Nguồn:/);
    const booking = screen.getByRole("heading", { name: "Đặt lịch" }).closest("article");
    if (!booking) throw new Error("Không thấy kịch bản Đặt lịch");

    await userEvent.click(within(booking).getByRole("button", { name: "Điền cấu hình inbound" }));
    expect(screen.getByLabelText("Số người gọi")).toHaveValue("0912345600");

    await startCall();
    expect(recorded.start[0]).toMatchObject({ direction: "inbound", caller_number: "0912345600" });

    await userEvent.click(within(booking).getByRole("button", { name: "Tôi muốn đặt lịch khám" }));
    expect(screen.getByLabelText("Lời người gọi")).toHaveValue("Tôi muốn đặt lịch khám");
  });

  it("reset clinic sau khi xác nhận: tạo Call ID mới và báo trạng thái lịch", async () => {
    backend();
    server.use(
      http.post("/demo-api/clinic-reset", () =>
        HttpResponse.json({
          reset: true,
          appointment: { appointment_id: "apt_00417", status: "SCHEDULED", version: 1 },
        }),
      ),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<CallPage />);
    await startCall();
    const oldCallId = screen.getByLabelText<HTMLInputElement>("Call ID").value;

    await userEvent.click(screen.getByRole("button", { name: "Reset clinic" }));

    expect(
      await screen.findByText(/Đã reset clinic · apt_00417: SCHEDULED v1/),
    ).toBeInTheDocument();
    expect(screen.getByLabelText("Call ID")).toBeEnabled();
    expect(screen.getByLabelText("Call ID")).not.toHaveValue(oldCallId);
    expect(screen.queryByText("Xin chào, em là trợ lý ảo của Vinmec.")).not.toBeInTheDocument();
  });

  it("huỷ hộp xác nhận thì không reset clinic", async () => {
    backend();
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<CallPage />);

    await userEvent.click(screen.getByRole("button", { name: "Reset clinic" }));

    // Không có handler cho /demo-api/clinic-reset: nếu có request, MSW làm test lỗi.
    expect(screen.queryByText(/Đã reset clinic/)).not.toBeInTheDocument();
  });
});
