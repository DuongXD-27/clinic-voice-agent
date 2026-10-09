import { describe, expect, it } from "vitest";

import {
  describeConnection,
  initialSession,
  isActive,
  liveKitReducer,
  type LiveKitAction,
  type LiveKitSession,
} from "./session";
import type { TranscriptLine } from "./transcript";

function run(...actions: LiveKitAction[]): LiveKitSession {
  return actions.reduce(liveKitReducer, initialSession);
}

const connected = run(
  { type: "connecting", step: "Đang lấy token…" },
  { type: "connected", roomName: "web-1", botPresent: false, at: 1 },
);

describe("liveKitReducer", () => {
  it("connecting cập nhật bước, connected bật mic và ghi nhật ký", () => {
    const connecting = run(
      { type: "connecting", step: "Đang lấy token…" },
      { type: "connecting", step: "Đang vào room…" },
    );
    expect(connecting).toMatchObject({ phase: "connecting", step: "Đang vào room…" });

    expect(connected).toMatchObject({ phase: "connected", roomName: "web-1", micEnabled: true });
    expect(connected.log).toEqual([
      { id: 1, at: 1, text: "Đã vào room web-1, microphone đang bật.", tone: "success" },
    ]);
  });

  it("bắt đầu cuộc gọi mới xoá nhật ký và thông báo cũ", () => {
    const ended = liveKitReducer(connected, { type: "disconnected", at: 2 });
    const again = liveKitReducer(ended, { type: "connecting", step: "Đang lấy token…" });

    expect(again.log).toEqual([]);
    expect(again.notice).toBeNull();
  });

  it("mất mạng rồi kết nối lại, không còn ai đang nói trong lúc gián đoạn", () => {
    const speaking = liveKitReducer(connected, { type: "speakers", bot: true, caller: false });
    const reconnecting = liveKitReducer(speaking, { type: "reconnecting", at: 2 });
    const back = liveKitReducer(reconnecting, { type: "reconnected", at: 3 });

    expect(reconnecting).toMatchObject({ phase: "reconnecting", speaking: { bot: false } });
    expect(isActive(reconnecting)).toBe(true);
    expect(back.phase).toBe("connected");
    expect(back.log.map((entry) => entry.tone)).toEqual(["success", "warning", "success"]);
  });

  it("ngắt kết nối về idle và tắt mọi cờ", () => {
    const busy = run(
      { type: "connecting", step: "x" },
      { type: "connected", roomName: "r", botPresent: true, at: 1 },
      { type: "speakers", bot: true, caller: true },
      { type: "audioBlocked", blocked: true },
      { type: "disconnected", at: 2 },
    );

    expect(busy).toMatchObject({
      phase: "idle",
      micEnabled: false,
      botPresent: false,
      speaking: { bot: false, caller: false },
      audioBlocked: false,
      notice: { tone: "info", text: "Cuộc gọi đã kết thúc." },
    });
  });

  it("lỗi khi kết nối quay về idle với thông báo lỗi", () => {
    const failed = run(
      { type: "connecting", step: "x" },
      { type: "failed", message: "LIVEKIT_URL chưa cấu hình", at: 5 },
    );

    expect(failed.phase).toBe("idle");
    expect(failed.notice).toEqual({ tone: "error", text: "LIVEKIT_URL chưa cấu hình" });
    expect(failed.log.at(-1)).toMatchObject({
      text: "Lỗi: LIVEKIT_URL chưa cấu hình",
      tone: "error",
    });
  });

  it("tắt mic thì bỏ cờ đang nói của người gọi", () => {
    const talking = liveKitReducer(connected, { type: "speakers", bot: false, caller: true });
    const muted = liveKitReducer(talking, { type: "micChanged", enabled: false, at: 2 });

    expect(muted).toMatchObject({ micEnabled: false, speaking: { caller: false } });
    expect(muted.log.at(-1)?.text).toBe("Đã tắt microphone.");
  });

  it("bot vào rồi rời phòng", () => {
    const joined = liveKitReducer(connected, { type: "botPresence", present: true, at: 2 });
    const left = liveKitReducer(
      liveKitReducer(joined, { type: "speakers", bot: true, caller: false }),
      { type: "botPresence", present: false, at: 3 },
    );

    expect(joined.botPresent).toBe(true);
    expect(left).toMatchObject({ botPresent: false, speaking: { bot: false } });
    expect(left.log.map((entry) => entry.text).slice(-2)).toEqual([
      "Bot đã vào phòng.",
      "Bot đã rời phòng.",
    ]);
  });

  it("ghi ASR bot thực sự dùng cho cuộc gọi", () => {
    const reported = liveKitReducer(connected, { type: "botAsr", provider: "gemini_live", at: 2 });

    expect(reported.log.at(-1)?.text).toBe("Bot dùng ASR: Gemini Live.");
  });

  it.each<[string, LiveKitSession, LiveKitAction]>([
    [
      "connected khi chưa connecting",
      initialSession,
      { type: "connected", roomName: "r", botPresent: false, at: 1 },
    ],
    ["reconnected khi đang connected", connected, { type: "reconnected", at: 1 }],
    ["disconnected khi đã idle", initialSession, { type: "disconnected", at: 1 }],
    ["speakers khi idle", initialSession, { type: "speakers", bot: true, caller: true }],
    ["mic không đổi", connected, { type: "micChanged", enabled: true, at: 1 }],
    ["speakers không đổi", connected, { type: "speakers", bot: false, caller: false }],
    ["connecting khi đang gọi", connected, { type: "connecting", step: "x" }],
  ])("bỏ qua %s", (_name, state, action) => {
    expect(liveKitReducer(state, action)).toBe(state);
  });
});

describe("transcript", () => {
  const bot = (
    turn: number,
    text: string,
    extra: Partial<TranscriptLine> = {},
  ): TranscriptLine => ({
    role: "bot",
    turn,
    text,
    confidence: null,
    state: "AWAITING_INTENT",
    ended: false,
    outcome: null,
    ...extra,
  });

  it("nối lời thoại, cập nhật state/outcome theo câu bot, ghi nhật ký khi bot kết thúc", () => {
    const state = [
      bot(0, "Xin chào", { state: "AWAITING_IDENTITY" }),
      { ...bot(1, "Tôi là An"), role: "caller" as const, state: null, confidence: 0.9 },
      bot(1, "Em đã xác nhận", { state: "ENDED", ended: true, outcome: "CONFIRMED" }),
    ].reduce(
      (current, line, index) =>
        liveKitReducer(current, { type: "transcript", line, at: 10 + index }),
      connected,
    );

    expect(state.transcript.map((line) => line.text)).toEqual([
      "Xin chào",
      "Tôi là An",
      "Em đã xác nhận",
    ]);
    expect(state).toMatchObject({ botState: "ENDED", outcome: "CONFIRMED" });
    expect(state.log.at(-1)).toMatchObject({
      text: "Bot kết thúc cuộc gọi: CONFIRMED.",
      tone: "success",
    });
  });

  it("giữ transcript sau khi ngắt để xem lại, xoá khi bắt đầu cuộc gọi mới", () => {
    const withLine = liveKitReducer(connected, {
      type: "transcript",
      line: bot(0, "Xin chào"),
      at: 2,
    });
    const ended = liveKitReducer(withLine, { type: "disconnected", at: 3 });
    const next = liveKitReducer(ended, { type: "connecting", step: "x" });

    expect(ended.transcript).toHaveLength(1);
    expect(next.transcript).toEqual([]);
    expect(next.botState).toBeNull();
  });

  it("bỏ qua transcript đến khi chưa vào room hoặc đã ngắt", () => {
    const action = { type: "transcript", line: bot(0, "muộn"), at: 1 } as const;

    expect(liveKitReducer(initialSession, action)).toBe(initialSession);
  });

  it("giữ câu chào bot gửi khi trình duyệt còn đang bật mic (chưa connected)", () => {
    const state = run(
      { type: "connecting", step: "Đang bật microphone…" },
      { type: "transcript", line: bot(0, "Xin chào"), at: 1 },
      { type: "connected", roomName: "web-1", botPresent: true, at: 2 },
    );

    expect(state.phase).toBe("connected");
    expect(state.transcript.map((line) => line.text)).toEqual(["Xin chào"]);
    expect(state.botState).toBe("AWAITING_INTENT");
  });
});

describe("describeConnection", () => {
  it.each([
    ["idle", initialSession, { tone: "neutral", label: "Chưa kết nối", pulse: false }],
    [
      "connecting",
      run({ type: "connecting", step: "Đang vào room…" }),
      { tone: "neutral", label: "Đang vào room…", pulse: true },
    ],
    ["connected", connected, { tone: "success", label: "Đã kết nối · web-1", pulse: false }],
    [
      "reconnecting",
      liveKitReducer(connected, { type: "reconnecting", at: 2 }),
      { tone: "warning", label: "Đang kết nối lại…", pulse: true },
    ],
  ] as const)("%s", (_phase, state, expected) => {
    expect(describeConnection(state)).toEqual(expected);
  });
});
