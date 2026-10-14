import { describe, expect, it } from "vitest";

import {
  describeTurn,
  initialStt,
  parseSttMessage,
  sttReducer,
  type SttAction,
  type SttMessage,
  type SttSession,
} from "./stt";

const encoder = new TextEncoder();

function message(kind: SttMessage["kind"], turn: number, text: string, extra = {}): SttAction {
  return {
    type: "message",
    message: { kind, turn, text, confidence: null, finalMs: null, ...extra },
  };
}

function run(...actions: SttAction[]): SttSession {
  const listening = sttReducer(
    sttReducer(initialStt, { type: "connecting", step: "Đang lấy token…" }),
    { type: "connected", workerPresent: true },
  );
  return actions.reduce(sttReducer, listening);
}

const view = (state: SttSession) => state.turns.map((turn) => [turn.status, turn.turn, turn.text]);

describe("sttReducer", () => {
  it("partial thay chữ của lượt đang nói, final chốt đúng dòng đó", () => {
    const state = run(
      message("partial", 1, "tôi"),
      message("partial", 1, "tôi muốn đổi"),
      message("final", 1, "tôi muốn đổi lịch", { confidence: 0.92, finalMs: 1200 }),
      message("partial", 2, "vâng"),
    );

    expect(view(state)).toEqual([
      ["final", 1, "tôi muốn đổi lịch"],
      ["live", 2, "vâng"],
    ]);
    expect(state.turns.map(describeTurn)[0]).toBe("Lượt 1 · 92% · chốt sau 1,2 s");
  });

  it("lượt bị pipeline bỏ vẫn hiện, lượt sau cùng số lượt thành dòng mới", () => {
    const state = run(
      message("partial", 1, "ừ"),
      message("dropped", 1, "ừ"),
      message("partial", 1, "có"),
      message("final", 1, "có"),
    );

    expect(view(state)).toEqual([
      ["dropped", 1, "ừ"],
      ["final", 1, "có"],
    ]);
    expect(new Set(state.turns.map((turn) => turn.id)).size).toBe(2);
  });

  it("kết cục của lượt trước tới sau khi lượt sau đã có chữ: đóng đúng dòng của nó", () => {
    const state = run(
      message("partial", 1, "tivi nói"),
      message("partial", 2, "tôi muốn"),
      message("dropped", 1, "tivi nói"),
      message("final", 2, "tôi muốn đặt lịch"),
    );

    expect(view(state)).toEqual([
      ["dropped", 1, "tivi nói"],
      ["final", 2, "tôi muốn đặt lịch"],
    ]);
  });

  it("bỏ partial tới muộn của lượt đã chốt", () => {
    const state = run(message("final", 1, "xin chào"), message("partial", 1, "xin"));

    expect(view(state)).toEqual([["final", 1, "xin chào"]]);
  });

  it("kết thúc giữa lúc đang nói: dòng tạm thời không còn là đang nghe; giữ lại để xem", () => {
    const state = sttReducer(run(message("partial", 1, "tôi muốn")), { type: "disconnected" });

    expect(state.phase).toBe("idle");
    expect(view(state)).toEqual([["dropped", 1, "tôi muốn"]]);
  });

  it("phiên mới xoá các lượt cũ và lỗi cũ", () => {
    const failed = sttReducer(run(message("final", 1, "a")), { type: "failed", message: "x" });
    const next = sttReducer(failed, { type: "connecting", step: "Đang lấy token…" });

    expect(next.turns).toEqual([]);
    expect(next.error).toBeNull();
  });
});

describe("parseSttMessage", () => {
  it("đọc tin của worker, bỏ qua tin sai dạng", () => {
    const ok = parseSttMessage(
      encoder.encode(
        JSON.stringify({
          type: "stt",
          kind: "final",
          turn: 2,
          text: "có",
          confidence: 0.8,
          final_ms: 900,
        }),
      ),
    );

    expect(ok).toEqual({ kind: "final", turn: 2, text: "có", confidence: 0.8, finalMs: 900 });
    expect(parseSttMessage(encoder.encode("not json"))).toBeNull();
    expect(
      parseSttMessage(encoder.encode(JSON.stringify({ type: "transcript", kind: "final" }))),
    ).toBeNull();
  });
});
