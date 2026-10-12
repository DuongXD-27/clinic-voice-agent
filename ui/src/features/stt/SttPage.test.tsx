import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { afterEach, describe, expect, it, vi } from "vitest";

import { server } from "../../test/server";
import { SttPage } from "./SttPage";

/** Room giả: ghi lại lời gọi SDK và cho test tự phát sự kiện như server LiveKit. */
const livekit = vi.hoisted(() => {
  type Handler = (...args: unknown[]) => void;

  class FakeRoom {
    static instances: FakeRoom[] = [];
    readonly handlers = new Map<string, Handler[]>();
    readonly remoteParticipants = new Map<string, unknown>([["worker", {}]]);
    state = "connected";
    readonly localParticipant = {
      identity: "web-me",
      setMicrophoneEnabled: vi.fn(() => Promise.resolve()),
    };
    readonly connect = vi.fn(() => Promise.resolve());
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
  ConnectionState: { Connected: "connected", Reconnecting: "reconnecting" },
  RoomEvent: {
    ParticipantConnected: "participantConnected",
    ParticipantDisconnected: "participantDisconnected",
    ParticipantAttributesChanged: "participantAttributesChanged",
    DataReceived: "dataReceived",
    Disconnected: "disconnected",
    MediaDevicesError: "mediaDevicesError",
  },
}));

const encoder = new TextEncoder();

function tokenEndpoint(): unknown[] {
  const bodies: unknown[] = [];
  server.use(
    http.post("/livekit/token", async ({ request }) => {
      bodies.push(await request.json());
      return HttpResponse.json({
        url: "wss://dev.livekit.cloud",
        room_name: "web-stt-1",
        token: "jwt",
        identity: "web-me",
      });
    }),
  );
  return bodies;
}

function room() {
  const instance = livekit.FakeRoom.instances.at(-1);
  if (!instance) throw new Error("Chưa tạo Room");
  return instance;
}

function data(topic: string, payload: object) {
  act(() => {
    room().emit(
      "dataReceived",
      encoder.encode(JSON.stringify(payload)),
      undefined,
      undefined,
      topic,
    );
  });
}

function stt(kind: string, turn: number, text: string, extra = {}) {
  data("callbot.stt", { type: "stt", kind, turn, text, ...extra });
}

const status = () => within(screen.getByRole("status", { name: "Trạng thái" }));

async function speak() {
  await userEvent.click(screen.getByRole("button", { name: "Nói" }));
  await status().findByText("Đang nghe");
}

afterEach(() => {
  livekit.FakeRoom.instances = [];
});

describe("SttPage", () => {
  it("bấm Nói: vào room chế độ STT với model đã chọn rồi nghe", async () => {
    const bodies = tokenEndpoint();
    render(<SttPage />);

    await userEvent.click(screen.getByRole("radio", { name: "ElevenLabs Realtime" }));
    await speak();

    expect(bodies).toEqual([{ mode: "stt", asr_provider: "elevenlabs_realtime" }]);
    expect(room().localParticipant.setMicrophoneEnabled).toHaveBeenCalledWith(true);
    expect(screen.getByRole("radio", { name: "Gemini Live" })).toBeDisabled();
    expect(screen.getByText("Đang nghe — hãy nói gì đó.")).toBeInTheDocument();
  });

  it("chữ của lượt đang nói thay dần, rồi chốt; lượt sau thành dòng mới", async () => {
    tokenEndpoint();
    render(<SttPage />);
    await speak();

    stt("partial", 1, "tôi muốn");
    expect(screen.getByText("tôi muốn")).toBeInTheDocument();
    expect(screen.getByText("Lượt 1 · đang nghe")).toBeInTheDocument();

    stt("partial", 1, "tôi muốn đổi lịch");
    stt("final", 1, "tôi muốn đổi lịch", { confidence: 0.9, final_ms: 1500 });
    stt("dropped", 2, "ừ");

    expect(screen.queryByText("tôi muốn")).not.toBeInTheDocument();
    expect(screen.getByText("Lượt 1 · 90% · chốt sau 1,5 s")).toBeInTheDocument();
    expect(screen.getByText("ừ")).toBeInTheDocument();
    expect(screen.getByText("Lượt 2 · không thành lượt")).toBeInTheDocument();
  });

  it("hiện model worker thực sự dùng, cảnh báo khi khác lựa chọn", async () => {
    tokenEndpoint();
    render(<SttPage />);
    await speak();

    act(() => {
      room().emit(
        "participantAttributesChanged",
        { asr_provider: "zipformer" },
        { identity: "agent" },
      );
    });

    expect(
      screen.getByText("Worker đang dùng ZipFormer — KHÁC lựa chọn Gemini Live."),
    ).toBeInTheDocument();
  });

  it("worker không tạo được model: báo lỗi, rời room, cho bấm Nói lại", async () => {
    tokenEndpoint();
    render(<SttPage />);
    await speak();

    data("callbot.status", { code: "ASR_UNAVAILABLE", message: "Thiếu ELEVENLABS_API_KEY." });

    expect(screen.getByRole("alert")).toHaveTextContent("Thiếu ELEVENLABS_API_KEY.");
    expect(room().disconnect).toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Nói" })).toBeEnabled();
  });

  it("worker rời phòng mà không kịp báo lỗi: sau ít giây trang tự dừng và báo", async () => {
    tokenEndpoint();
    render(<SttPage />);
    await speak();

    vi.useFakeTimers();
    try {
      act(() => {
        room().remoteParticipants.clear();
        room().emit("participantDisconnected", { identity: "agent" });
      });
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
      act(() => {
        vi.advanceTimersByTime(3000);
      });
    } finally {
      vi.useRealTimers();
    }

    expect(screen.getByRole("alert")).toHaveTextContent("Worker đã rời phòng");
    expect(room().disconnect).toHaveBeenCalled();
  });

  it("mạng chập chờn (kết nối lại toàn bộ): worker quay lại thì không báo lỗi", async () => {
    tokenEndpoint();
    render(<SttPage />);
    await speak();

    vi.useFakeTimers();
    try {
      act(() => {
        room().remoteParticipants.clear();
        room().emit("participantDisconnected", { identity: "agent" });
        room().state = "reconnecting";
      });
      act(() => {
        room().remoteParticipants.set("worker", {});
        room().state = "connected";
        room().emit("participantConnected", { identity: "agent" });
        vi.advanceTimersByTime(3000);
      });
    } finally {
      vi.useRealTimers();
    }

    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(status().getByText("Đang nghe")).toBeInTheDocument();
  });

  it("Kết thúc: ngắt room, giữ các lượt đã có", async () => {
    tokenEndpoint();
    render(<SttPage />);
    await speak();
    stt("final", 1, "xin chào");

    await userEvent.click(screen.getByRole("button", { name: "Kết thúc" }));

    expect(room().disconnect).toHaveBeenCalled();
    expect(status().getByText("Chưa kết nối")).toBeInTheDocument();
    expect(screen.getByText("xin chào")).toBeInTheDocument();
  });
});
