import { describe, expect, it } from "vitest";

import { parseTranscript, toChatMessage, type TranscriptLine } from "./transcript";

const encode = (value: unknown) => new TextEncoder().encode(JSON.stringify(value));

const caller: TranscriptLine = {
  role: "caller",
  turn: 1,
  text: "Tôi là Nguyễn Văn A",
  confidence: 0.914,
  state: null,
  ended: false,
  outcome: null,
};

describe("parseTranscript", () => {
  it("đọc lời người gọi kèm độ tin cậy ASR (payload giống call_bridge.py)", () => {
    const line = parseTranscript(
      encode({
        type: "transcript",
        role: "caller",
        turn: 1,
        text: "Tôi là Nguyễn Văn A",
        confidence: 0.914,
      }),
    );

    expect(line).toEqual(caller);
  });

  it("đọc câu bot kèm state, ended, outcome", () => {
    const line = parseTranscript(
      encode({
        type: "transcript",
        role: "bot",
        turn: 2,
        text: "Em đã xác nhận lịch.",
        state: "ENDED",
        ended: true,
        outcome: "CONFIRMED",
      }),
    );

    expect(line).toMatchObject({ role: "bot", state: "ENDED", ended: true, outcome: "CONFIRMED" });
  });

  it.each([
    ["không phải JSON", new TextEncoder().encode("xin chào")],
    ["sai type", encode({ type: "other", role: "bot", turn: 0, text: "x" })],
    ["role lạ", encode({ type: "transcript", role: "agent", turn: 0, text: "x" })],
    ["thiếu turn", encode({ type: "transcript", role: "bot", text: "x" })],
    ["text không phải chuỗi", encode({ type: "transcript", role: "bot", turn: 0, text: 1 })],
  ])("bỏ qua gói %s", (_name, payload) => {
    expect(parseTranscript(payload)).toBeNull();
  });
});

describe("toChatMessage", () => {
  it("người gọi: lượt và độ tin cậy ASR làm tròn phần trăm", () => {
    expect(toChatMessage(caller, 1)).toEqual({
      id: "1-caller-1",
      role: "caller",
      text: "Tôi là Nguyễn Văn A",
      meta: "NGƯỜI GỌI · lượt 1 · ASR 91%",
    });
  });

  it("bot: lượt, state và outcome nếu có", () => {
    const message = toChatMessage(
      {
        ...caller,
        role: "bot",
        turn: 0,
        text: "Xin chào",
        confidence: null,
        state: "AWAITING_IDENTITY",
      },
      0,
    );

    expect(message.meta).toBe("BOT · lượt 0 · AWAITING_IDENTITY");
  });

  it("ASR rỗng vẫn hiện một dòng để trace được", () => {
    expect(toChatMessage({ ...caller, text: "", confidence: null }, 3)).toMatchObject({
      text: "(không nghe rõ)",
      meta: "NGƯỜI GỌI · lượt 1",
    });
  });
});

describe("parseTranscript: trích xuất kèm câu bot (demo_debug)", () => {
  const botLine = (extraction: unknown) =>
    parseTranscript(encode({ type: "transcript", role: "bot", turn: 2, text: "Dạ", extraction }));

  it("đọc trích xuất của lượt (payload giống call_bridge.py)", () => {
    const line = botLine({
      transcript: "thôi hủy giúp tôi",
      silent: false,
      fields: [{ field: "intent", value: "CANCEL", span: "hủy giúp tôi", provenance: "FALLBACK" }],
      model: { provider: "typesafe", name: "jev-1.13.0", status: "OK", backup_for: null },
    });

    expect(line?.extraction).toEqual({
      turn: 2,
      fields: {
        transcript: "thôi hủy giúp tôi",
        silent: false,
        fields: [
          { field: "intent", value: "CANCEL", span: "hủy giúp tôi", provenance: "FALLBACK" },
        ],
        model: { provider: "typesafe", name: "jev-1.13.0", status: "OK", backupFor: null },
      },
    });
  });

  it("lượt không qua bước trích xuất: fields null", () => {
    expect(botLine(null)?.extraction).toEqual({ turn: 2, fields: null });
  });

  it("sai dạng: đánh dấu invalid, không lẫn với lượt không trích xuất", () => {
    expect(botLine({ transcript: "x" })?.extraction).toBe("invalid");
  });

  it("worker không gửi (tắt demo_debug / bản cũ): không có trường extraction", () => {
    const line = parseTranscript(encode({ type: "transcript", role: "bot", turn: 2, text: "Dạ" }));
    expect(line && "extraction" in line).toBe(false);
  });
});
