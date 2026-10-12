import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { server } from "../../test/server";
import { LiveKitPage } from "./LiveKitPage";

/** Room giả: ghi lại lời gọi SDK và cho test tự phát sự kiện như server LiveKit. */
const livekit = vi.hoisted(() => {
  type Handler = (...args: unknown[]) => void;

  class FakeRoom {
    static instances: FakeRoom[] = [];
    /** Lỗi cho lần bật mic kế tiếp (vd. người dùng từ chối quyền). */
    static micError: Error | null = null;
    readonly handlers = new Map<string, Handler[]>();
    readonly remoteParticipants = new Map<string, unknown>();
    canPlaybackAudio = true;
    readonly localParticipant = {
      identity: "web-me",
      isMicrophoneEnabled: false,
      setMicrophoneEnabled: vi.fn((enabled: boolean) => {
        const error = FakeRoom.micError;
        FakeRoom.micError = null;
        if (error) return Promise.reject(error);
        this.localParticipant.isMicrophoneEnabled = enabled;
        return Promise.resolve();
      }),
    };
    readonly connect = vi.fn(() => Promise.resolve());
    readonly startAudio = vi.fn(() => Promise.resolve());
    readonly disconnect = vi.fn(() => {
      this.emit("disconnected");
      return Promise.resolve();
    });

    constructor() {
      FakeRoom.instances.push(this);
    }

    on(event: string, handler: Handler) {
      this.handlers.set(event, [...(this.handlers.get(event) ?? []), handler]);
      return this;
    }

    removeAllListeners() {
      this.handlers.clear();
      return this;
    }

    emit(event: string, ...args: unknown[]) {
      for (const handler of this.handlers.get(event) ?? []) handler(...args);
    }
  }

  return { FakeRoom };
});

vi.mock("livekit-client", () => ({
  Room: livekit.FakeRoom,
  RoomEvent: {
    TrackSubscribed: "trackSubscribed",
    ParticipantConnected: "participantConnected",
    ParticipantDisconnected: "participantDisconnected",
    ActiveSpeakersChanged: "activeSpeakersChanged",
    Reconnecting: "reconnecting",
    Reconnected: "reconnected",
    Disconnected: "disconnected",
    AudioPlaybackStatusChanged: "audioPlaybackChanged",
    MediaDevicesError: "mediaDevicesError",
    DataReceived: "dataReceived",
  },
  Track: { Kind: { Audio: "audio" } },
}));

const TOKEN = {
  url: "wss://dev.livekit.cloud",
  room_name: "web-room-1",
  token: "jwt",
  identity: "web-me",
};

const FIXTURES = {
  source: "mock",
  appointments: [
    { appointment_id: "apt_00417", status: "TRANSFERRED", display_name: "N. V. A." },
    { appointment_id: "apt_00418", status: "SCHEDULED", display_name: "T. T. B." },
  ],
  phones: [{ phone: "0912345600", display_name: "N. V. A." }],
};

function tokenEndpoint(): unknown[] {
  const bodies: unknown[] = [];
  server.use(
    http.post("/livekit/token", async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json(TOKEN);
    }),
  );
  return bodies;
}

function room() {
  const instance = livekit.FakeRoom.instances.at(-1);
  if (!instance) throw new Error("Chưa tạo Room");
  return instance;
}

function emit(event: string, ...args: unknown[]) {
  act(() => {
    room().emit(event, ...args);
  });
}

function connection() {
  return within(screen.getByRole("status", { name: "Trạng thái kết nối" }));
}

async function connect() {
  await userEvent.click(screen.getByRole("button", { name: "Bắt đầu cuộc gọi" }));
  await connection().findByText("Đã kết nối · web-room-1");
}

beforeEach(() => {
  server.use(http.get("/demo-api/clinic-fixtures", () => HttpResponse.json(FIXTURES)));
});

afterEach(() => {
  livekit.FakeRoom.instances = [];
  livekit.FakeRoom.micError = null;
});

describe("LiveKitPage", () => {
  it("lấy token, vào room, bật mic rồi theo dõi bot", async () => {
    const bodies = tokenEndpoint();
    render(<LiveKitPage />);

    await connect();

    expect(bodies).toEqual([{ direction: "inbound", caller_number: "0912345600" }]);
    expect(room().connect).toHaveBeenCalledWith(TOKEN.url, TOKEN.token);
    expect(room().localParticipant.setMicrophoneEnabled).toHaveBeenCalledWith(true);
    expect(screen.getByLabelText("Bot Vinmec: Đang chờ bot vào phòng…")).toBeInTheDocument();
    expect(screen.getByLabelText("Số người gọi")).toBeDisabled();

    emit("participantConnected");
    expect(screen.getByLabelText("Bot Vinmec: Đang nghe")).toBeInTheDocument();

    emit("activeSpeakersChanged", [{ identity: "agent-1" }]);
    expect(screen.getByLabelText("Bot Vinmec: Đang nói")).toBeInTheDocument();
    expect(screen.getByLabelText("Bạn: Mic đang bật")).toBeInTheDocument();

    emit("activeSpeakersChanged", [{ identity: "web-me" }]);
    expect(screen.getByLabelText("Bạn: Đang nói")).toBeInTheDocument();
    expect(screen.getByText("Bot đã vào phòng.")).toBeInTheDocument();
  });

  it("hiện lời thoại worker gửi qua data channel, kèm state và outcome", async () => {
    tokenEndpoint();
    render(<LiveKitPage />);
    await connect();
    const transcript = (payload: object, topic = "callbot.transcript") => {
      emit(
        "dataReceived",
        new TextEncoder().encode(JSON.stringify(payload)),
        undefined,
        undefined,
        topic,
      );
    };

    transcript({
      type: "transcript",
      role: "bot",
      turn: 0,
      text: "Dạ Vinmec xin nghe",
      state: "AWAITING_IDENTITY",
      ended: false,
      outcome: null,
    });
    transcript({
      type: "transcript",
      role: "caller",
      turn: 1,
      text: "Tôi là Nguyễn Văn A",
      confidence: 0.87,
    });
    transcript({
      type: "transcript",
      role: "bot",
      turn: 1,
      text: "Dạ, em chuyển máy",
      state: "ENDED",
      ended: true,
      outcome: "TRANSFERRED",
    });
    // Topic khác (vd. dữ liệu của SDK) không lẫn vào hội thoại.
    transcript({ type: "transcript", role: "bot", turn: 9, text: "không hiện" }, "other.topic");

    const chat = within(screen.getByLabelText("Hội thoại"));
    expect(chat.getByText("Dạ Vinmec xin nghe")).toBeInTheDocument();
    expect(chat.getByText("Tôi là Nguyễn Văn A")).toBeInTheDocument();
    expect(chat.getByText("NGƯỜI GỌI · lượt 1 · ASR 87%")).toBeInTheDocument();
    expect(chat.getByText("BOT · lượt 1 · ENDED · TRANSFERRED")).toBeInTheDocument();
    expect(chat.queryByText("không hiện")).not.toBeInTheDocument();
    expect(screen.getByText("TRANSFERRED", { selector: "dd *" })).toBeInTheDocument();

    // Kết thúc cuộc gọi vẫn giữ lời thoại để xem lại.
    await userEvent.click(screen.getByRole("button", { name: "Kết thúc" }));
    expect(chat.getByText("Tôi là Nguyễn Văn A")).toBeInTheDocument();
  });

  it("hiện trích xuất của lượt như trang HTTP, kèm model đã đọc câu", async () => {
    tokenEndpoint();
    render(<LiveKitPage />);
    await connect();
    const send = (payload: object) => {
      emit(
        "dataReceived",
        new TextEncoder().encode(JSON.stringify(payload)),
        undefined,
        undefined,
        "callbot.transcript",
      );
    };
    const panel = () => {
      const card = screen.getByText("Trích xuất lượt gần nhất").closest("section");
      if (!card) throw new Error("Không thấy card trích xuất");
      return within(card);
    };

    expect(panel().getByText("Chưa có lượt nào.")).toBeInTheDocument();

    send({
      type: "extraction",
      turn: 1,
      extraction: {
        transcript: "thôi hủy giúp tôi",
        silent: false,
        fields: [
          { field: "intent", value: "CANCEL", span: "hủy giúp tôi", provenance: "FALLBACK" },
        ],
        model: { provider: "typesafe", name: "jev-1.13.0", status: "OK", backup_for: null },
      },
    });

    expect(panel().getByText("hủy giúp tôi", { selector: "mark" })).toBeInTheDocument();
    expect(panel().getByText("Ý định")).toBeInTheDocument();
    expect(panel().getByText("Jev")).toBeInTheDocument();
    expect(panel().getByText("jev-1.13.0")).toBeInTheDocument();
    expect(panel().getByText("OK")).toBeInTheDocument();
    expect(panel().queryByText(/dự phòng/)).not.toBeInTheDocument();

    // Jev lỗi dịch vụ, OpenAI dự phòng trả lời: phải báo rõ.
    send({
      type: "extraction",
      turn: 2,
      extraction: {
        transcript: "vâng",
        silent: false,
        fields: [],
        model: { provider: "openai", name: "gpt-6-luna", status: "OK", backup_for: "typesafe" },
      },
    });
    expect(panel().getByText("OpenAI")).toBeInTheDocument();
    expect(panel().getByText("dự phòng — Jev lỗi")).toBeInTheDocument();

    // Lượt chỉ dùng luật.
    send({
      type: "extraction",
      turn: 3,
      extraction: { transcript: "vâng", silent: false, fields: [], model: null },
    });
    expect(panel().getByText("Model đọc câu: không gọi — chỉ dùng luật.")).toBeInTheDocument();
  });

  it("worker cũ không gửi trích xuất: báo thay vì để trống mãi", async () => {
    tokenEndpoint();
    render(<LiveKitPage />);
    await connect();

    emit(
      "dataReceived",
      new TextEncoder().encode(
        JSON.stringify({ type: "transcript", role: "bot", turn: 1, text: "Dạ", state: "X" }),
      ),
      undefined,
      undefined,
      "callbot.transcript",
    );

    expect(
      screen.getByText("Bot không gửi trích xuất: cuộc gọi có thể vào worker cũ."),
    ).toBeInTheDocument();
  });

  it("tắt rồi bật lại microphone", async () => {
    tokenEndpoint();
    render(<LiveKitPage />);
    await connect();

    await userEvent.click(screen.getByRole("button", { name: "Tắt mic" }));
    expect(room().localParticipant.setMicrophoneEnabled).toHaveBeenLastCalledWith(false);
    expect(screen.getByLabelText("Bạn: Đã tắt mic")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Bật mic" }));
    expect(screen.getByLabelText("Bạn: Mic đang bật")).toBeInTheDocument();
  });

  it("kết thúc cuộc gọi: ngắt room và mở lại cấu hình", async () => {
    tokenEndpoint();
    render(<LiveKitPage />);
    await connect();

    await userEvent.click(screen.getByRole("button", { name: "Kết thúc" }));

    expect(room().disconnect).toHaveBeenCalled();
    expect(connection().getByText("Chưa kết nối")).toBeInTheDocument();
    expect(screen.getByText("Cuộc gọi đã kết thúc.")).toBeInTheDocument();
    expect(screen.getByLabelText("Số người gọi")).toBeEnabled();
    expect(screen.getByRole("button", { name: "Bắt đầu cuộc gọi" })).toBeEnabled();
  });

  it("mất mạng rồi tự kết nối lại", async () => {
    tokenEndpoint();
    render(<LiveKitPage />);
    await connect();

    emit("reconnecting");
    expect(connection().getByText("Đang kết nối lại…")).toBeInTheDocument();
    emit("reconnected");
    expect(connection().getByText("Đã kết nối · web-room-1")).toBeInTheDocument();
  });

  it("server chưa cấu hình LiveKit: hiện thông báo của backend, không tạo room", async () => {
    server.use(
      http.post("/livekit/token", () =>
        HttpResponse.json(
          { detail: { code: "LIVEKIT_NOT_CONFIGURED", message: "LIVEKIT_URL chưa cấu hình" } },
          { status: 503 },
        ),
      ),
    );
    render(<LiveKitPage />);

    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu cuộc gọi" }));

    expect(await screen.findByText("LIVEKIT_URL chưa cấu hình")).toBeInTheDocument();
    expect(livekit.FakeRoom.instances).toHaveLength(0);
    expect(connection().getByText("Chưa kết nối")).toBeInTheDocument();
  });

  it("bị từ chối quyền microphone: ngắt room, giữ thông báo lỗi dễ hiểu", async () => {
    tokenEndpoint();
    render(<LiveKitPage />);
    livekit.FakeRoom.micError = Object.assign(new Error("Permission denied"), {
      name: "NotAllowedError",
    });

    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu cuộc gọi" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      /Trình duyệt không cho dùng microphone/,
    );
    expect(room().disconnect).toHaveBeenCalled();
    // Listener đã gỡ trước khi ngắt: thông báo lỗi không bị "Cuộc gọi đã kết thúc." đè.
    expect(screen.queryByText("Cuộc gọi đã kết thúc.")).not.toBeInTheDocument();
  });

  it("trình duyệt chặn phát audio: hiện nút bật âm thanh", async () => {
    tokenEndpoint();
    render(<LiveKitPage />);
    await connect();

    room().canPlaybackAudio = false;
    emit("audioPlaybackChanged");
    await userEvent.click(screen.getByRole("button", { name: "Bật âm thanh" }));

    expect(room().startAudio).toHaveBeenCalledTimes(2);
  });

  it("outbound chọn lịch hẹn từ clinic, kèm trạng thái như trang gọi HTTP", async () => {
    const bodies = tokenEndpoint();
    let authorization: string | null = null;
    server.use(
      http.get("/demo-api/clinic-fixtures", ({ request }) => {
        authorization = request.headers.get("Authorization");
        return HttpResponse.json(FIXTURES);
      }),
    );
    render(<LiveKitPage />);

    await userEvent.type(screen.getByLabelText("API key"), "sk_test");
    await userEvent.tab();
    await userEvent.click(screen.getByRole("radio", { name: "Outbound · bot gọi" }));
    const select = screen.getByLabelText("Appointment ID");
    await screen.findByRole("option", { name: "apt_00418 · SCHEDULED · T. T. B." });
    expect(authorization).toBe("Bearer sk_test");
    expect(screen.getByText(/Nguồn: clinic mock · 2 lịch hẹn/)).toBeInTheDocument();

    await userEvent.selectOptions(select, "apt_00418");
    await connect();

    expect(bodies).toEqual([{ direction: "outbound", appointment_id: "apt_00418" }]);
    expect(select).toBeDisabled();
  });

  it("inbound chọn số người gọi từ clinic như trang gọi HTTP, hoặc nhập số khác", async () => {
    const bodies = tokenEndpoint();
    server.use(
      http.get("/demo-api/clinic-fixtures", () =>
        HttpResponse.json({
          ...FIXTURES,
          phones: [...FIXTURES.phones, { phone: "0987654321", display_name: "T. T. B." }],
        }),
      ),
    );
    render(<LiveKitPage />);

    const select = screen.getByLabelText("Số người gọi");
    await screen.findByRole("option", { name: "0987654321 · T. T. B." });
    expect(select).toHaveValue("0912345600");
    expect(screen.queryByLabelText("Số điện thoại người gọi")).not.toBeInTheDocument();

    await userEvent.selectOptions(select, "0987654321");
    await connect();
    expect(bodies).toEqual([{ direction: "inbound", caller_number: "0987654321" }]);
    expect(select).toBeDisabled();

    // Số không có trong clinic: gõ tay; để trống là kịch bản chuyển máy ngay lượt đầu.
    await userEvent.click(screen.getByRole("button", { name: "Kết thúc" }));
    await userEvent.selectOptions(select, "Nhập số khác…");
    expect(screen.getByLabelText("Số điện thoại người gọi")).toHaveValue("");
    await connect();
    expect(bodies.at(-1)).toEqual({ direction: "inbound", caller_number: null });
  });

  it("reset clinic theo lịch đang chọn rồi tải lại danh sách; khoá khi đang gọi", async () => {
    tokenEndpoint();
    const resets: unknown[] = [];
    let fixtureLoads = 0;
    server.use(
      http.get("/demo-api/clinic-fixtures", () => {
        fixtureLoads += 1;
        return HttpResponse.json(FIXTURES);
      }),
      http.post("/demo-api/clinic-reset", async ({ request }) => {
        resets.push(await request.json());
        return HttpResponse.json({
          reset: true,
          appointment: { appointment_id: "apt_00418", status: "SCHEDULED", version: 1 },
        });
      }),
    );
    vi.spyOn(window, "confirm").mockReturnValue(true);
    render(<LiveKitPage />);
    await userEvent.click(screen.getByRole("radio", { name: "Outbound · bot gọi" }));
    await screen.findByRole("option", { name: "apt_00418 · SCHEDULED · T. T. B." });
    await userEvent.selectOptions(screen.getByLabelText("Appointment ID"), "apt_00418");

    await userEvent.click(screen.getByRole("button", { name: "Reset clinic" }));

    expect(
      await screen.findByText("Đã reset clinic · apt_00418: SCHEDULED v1."),
    ).toBeInTheDocument();
    expect(resets).toEqual([{ appointment_id: "apt_00418" }]);
    expect(fixtureLoads).toBe(2);

    await connect();
    expect(screen.getByRole("button", { name: "Reset clinic" })).toBeDisabled();
  });

  it("huỷ hộp xác nhận thì không reset clinic", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false);
    render(<LiveKitPage />);

    await userEvent.click(screen.getByRole("button", { name: "Reset clinic" }));

    // Không có handler cho /demo-api/clinic-reset: nếu có request, MSW làm test lỗi.
    expect(screen.queryByText(/Đã reset clinic/)).not.toBeInTheDocument();
  });

  it("worker không mở được cuộc gọi outbound: rời room, hiện lỗi của worker", async () => {
    const bodies = tokenEndpoint();
    render(<LiveKitPage />);
    await userEvent.click(screen.getByRole("radio", { name: "Outbound · bot gọi" }));
    await connect();

    emit(
      "dataReceived",
      new TextEncoder().encode(
        JSON.stringify({ code: "OUTBOUND_START_FAILED", message: "Không lấy được lịch hẹn" }),
      ),
      undefined,
      undefined,
      "callbot.status",
    );

    expect(bodies).toEqual([{ direction: "outbound", appointment_id: "apt_00417" }]);
    expect(room().disconnect).toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent("Không lấy được lịch hẹn");
    expect(connection().getByText("Chưa kết nối")).toBeInTheDocument();
    expect(screen.queryByText("Cuộc gọi đã kết thúc.")).not.toBeInTheDocument();
  });

  it("rời trang khi đang chờ token: không vào room, không bật mic", async () => {
    let releaseToken: () => void = () => undefined;
    const tokenRequested = new Promise<void>((requested) => {
      server.use(
        http.post("/livekit/token", async () => {
          requested();
          await new Promise<void>((resolve) => {
            releaseToken = resolve;
          });
          return HttpResponse.json(TOKEN);
        }),
      );
    });
    const { unmount } = render(<LiveKitPage />);

    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu cuộc gọi" }));
    await tokenRequested;
    unmount();
    releaseToken();
    await new Promise((resolve) => setTimeout(resolve, 50));

    expect(livekit.FakeRoom.instances).toHaveLength(0);
  });
});
