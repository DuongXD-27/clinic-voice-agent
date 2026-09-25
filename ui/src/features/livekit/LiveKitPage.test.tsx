import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

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

  it("outbound thiếu Appointment ID: chặn trước khi gọi API", async () => {
    render(<LiveKitPage />);

    await userEvent.click(screen.getByRole("radio", { name: "Outbound · bot gọi" }));
    await userEvent.clear(screen.getByLabelText("Appointment ID"));
    await userEvent.click(screen.getByRole("button", { name: "Bắt đầu cuộc gọi" }));

    // Không có handler /livekit/token: nếu có request, MSW làm test lỗi.
    expect(await screen.findByText("Cuộc gọi outbound cần Appointment ID.")).toBeInTheDocument();
  });
});
