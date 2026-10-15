import { describe, expect, it } from "vitest";

import { readDemoDebug } from "../../../lib/api/demoDebug";
import {
  callPhase,
  callReducer,
  canSend,
  canStart,
  describeCall,
  initialSession,
  isBusy,
  isConfigLocked,
  type CallAction,
  type CallSession,
  type Reply,
} from "./callMachine";

function reply(overrides: Partial<Reply> = {}): Reply {
  return {
    utterance: "Xin chào",
    audioUrl: null,
    state: "AWAITING_IDENTITY",
    debug: readDemoDebug(null),
    elapsedMs: 10,
    exchange: { method: "POST", path: "/v1/calls", request: {}, status: 200, response: {} },
    ...overrides,
  };
}

function run(...actions: CallAction[]): CallSession {
  return actions.reduce(callReducer, initialSession);
}

const started = run({ type: "start" }, { type: "started", callId: "c1", reply: reply() });

function turnDone(
  turn: number,
  overrides: Partial<Extract<CallAction, { type: "turnDone" }>> = {},
): CallAction {
  return {
    type: "turnDone",
    turn,
    caller: { text: "Tôi là An", audioUrl: null },
    reply: reply({ state: "AWAITING_INTENT" }),
    ended: false,
    outcome: null,
    ...overrides,
  };
}

describe("callReducer", () => {
  it("mở cuộc gọi: lời chào là lượt 0, lượt kế tiếp là 1", () => {
    expect(started.phase).toBe("active");
    expect(started.nextTurn).toBe(1);
    expect(started.messages).toEqual([
      expect.objectContaining({ id: "0-bot", role: "bot", text: "Xin chào", turn: 0 }),
    ]);
    expect(started.botState).toBe("AWAITING_IDENTITY");
    expect(started.callId).toBe("c1");
  });

  it("một lượt thêm câu người gọi rồi câu bot, lưu trích xuất và tăng lượt", () => {
    const state = callReducer(callReducer(started, { type: "turnSent" }), turnDone(1));

    expect(state.phase).toBe("active");
    expect(state.nextTurn).toBe(2);
    expect(state.messages.map((message) => message.id)).toEqual(["0-bot", "1-caller", "1-bot"]);
    expect(state.extraction).toEqual({ turn: 1, fields: null });
    expect(state.botState).toBe("AWAITING_INTENT");
  });

  it("lượt kết thúc chuyển sang ended và ghi outcome", () => {
    const state = callReducer(
      callReducer(started, { type: "turnSent" }),
      turnDone(1, { ended: true, outcome: "CONFIRMED" }),
    );

    expect(state.phase).toBe("ended");
    expect(state.outcome).toBe("CONFIRMED");
    expect(state.notice).toEqual({ tone: "success", text: "Cuộc gọi đã kết thúc: CONFIRMED." });
  });

  it("lỗi khi mở cuộc gọi quay về idle, giữ exchange", () => {
    const exchange = { method: "POST", path: "/v1/calls", request: {}, status: 503, response: {} };
    const state = run({ type: "start" }, { type: "failed", message: "Clinic lỗi", exchange });

    expect(state.phase).toBe("idle");
    expect(state.callId).toBeNull();
    expect(state.exchange).toBe(exchange);
    expect(state.notice).toEqual({ tone: "error", text: "Clinic lỗi" });
  });

  it("lỗi khi gửi lượt quay về active, không tăng lượt", () => {
    const state = callReducer(callReducer(started, { type: "turnSent" }), {
      type: "failed",
      message: "Hết thời gian",
      exchange: null,
    });

    expect(state.phase).toBe("active");
    expect(state.nextTurn).toBe(1);
    expect(state.exchange).toBe(started.exchange);
  });

  it.each<[string, CallSession, CallAction]>([
    ["start khi đang gọi", started, { type: "start" }],
    ["started khi chưa bắt đầu", initialSession, { type: "started", callId: "c1", reply: reply() }],
    ["hangup khi chưa gọi", initialSession, { type: "hangup" }],
    ["hangup khi đang mở cuộc gọi", run({ type: "start" }), { type: "hangup" }],
    ["turnSent khi chưa mở cuộc gọi", initialSession, { type: "turnSent" }],
    ["turnDone khi không chờ lượt nào", started, turnDone(1)],
    ["turnDone sai số lượt", callReducer(started, { type: "turnSent" }), turnDone(5)],
  ])("bỏ qua %s", (_name, state, action) => {
    expect(callReducer(state, action)).toBe(state);
  });

  it("không gửi thêm lượt sau khi kết thúc", () => {
    const ended = callReducer(
      callReducer(started, { type: "turnSent" }),
      turnDone(1, { ended: true, outcome: "UNREACHABLE" }),
    );

    expect(callReducer(ended, { type: "turnSent" })).toBe(ended);
  });

  it("gác máy giữa chừng: ended, giữ hội thoại, bỏ lượt đang chờ", () => {
    const sending = callReducer(started, { type: "turnSent" });
    const ended = callReducer(sending, { type: "hangup" });

    expect(ended.phase).toBe("ended");
    expect(ended.messages).toBe(started.messages);
    expect(ended.notice?.text).toMatch(/Đã kết thúc cuộc gọi/);
    expect(callReducer(ended, turnDone(1))).toBe(ended);
  });

  it("gọi tiếp sau khi kết thúc: xoá hội thoại cũ", () => {
    const ended = callReducer(started, { type: "hangup" });
    const again = callReducer(ended, { type: "start" });

    expect(again).toMatchObject({ phase: "starting", messages: [], callId: null });
  });

  it("reset về trạng thái ban đầu từ mọi pha", () => {
    expect(callReducer(started, { type: "reset" })).toBe(initialSession);
  });
});

describe("selectors", () => {
  it.each([
    ["idle", initialSession, { locked: false, start: true, send: false, busy: false }],
    ["starting", run({ type: "start" }), { locked: true, start: false, send: false, busy: true }],
    ["active", started, { locked: true, start: false, send: true, busy: false }],
    [
      "sending",
      callReducer(started, { type: "turnSent" }),
      { locked: true, start: false, send: false, busy: true },
    ],
    [
      "ended",
      callReducer(started, { type: "hangup" }),
      { locked: false, start: true, send: false, busy: false },
    ],
  ] as const)("%s", (_phase, state, expected) => {
    expect({
      locked: isConfigLocked(state),
      start: canStart(state),
      send: canSend(state),
      busy: isBusy(state),
    }).toEqual(expected);
  });
});

describe("thanh trạng thái và nút gọi", () => {
  it.each([
    ["idle", initialSession, "idle", "Chưa gọi"],
    ["starting", run({ type: "start" }), "connecting", "Đang mở cuộc gọi…"],
    ["active", started, "active", "Đang gọi · c1"],
    ["sending", callReducer(started, { type: "turnSent" }), "active", "Bot đang trả lời lượt 1…"],
    ["ended", callReducer(started, { type: "hangup" }), "idle", "Đã kết thúc · c1"],
  ] as const)("%s", (_phase, state, phase, label) => {
    expect(callPhase(state)).toBe(phase);
    expect(describeCall(state).label).toBe(label);
  });
});
