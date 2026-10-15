import { describe, expect, it } from "vitest";

import {
  formatTiming,
  parseNBest,
  parseTiming,
  parseTranscript,
  toChatMessage,
  type TranscriptLine,
} from "./transcript";

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

describe("parseNBest", () => {
  it("đọc top N phương án theo từng đoạn (payload giống call_bridge.py)", () => {
    const update = parseNBest(
      encode({
        type: "nbest",
        turn: 2,
        segments: [
          [
            { text: "TÔI LÀ NGUYỄN VĂN AN", log_prob: -0.41, share: 0.72 },
            { text: "TÔI LÀ NGUYỄN VĂN A", log_prob: -1.35, share: 0.28 },
          ],
        ],
      }),
    );

    expect(update).toEqual({
      turn: 2,
      segments: [
        [
          { text: "TÔI LÀ NGUYỄN VĂN AN", logProb: -0.41, share: 0.72 },
          { text: "TÔI LÀ NGUYỄN VĂN A", logProb: -1.35, share: 0.28 },
        ],
      ],
    });
  });

  it.each([
    ["gói transcript", encode({ type: "transcript", role: "bot", turn: 0, text: "x" })],
    ["thiếu turn", encode({ type: "nbest", segments: [[{ text: "x", log_prob: 0, share: 1 }]] })],
    ["phương án sai dạng", encode({ type: "nbest", turn: 1, segments: [[{ text: 1 }]] })],
  ])("bỏ qua %s", (_name, payload) => {
    expect(parseNBest(payload)).toBeNull();
  });
});

describe("toChatMessage với top N", () => {
  it("hiện từng phương án kèm log-xác suất và tỉ lệ", () => {
    const message = toChatMessage(
      { ...caller, nbest: [[{ text: "TÔI LÀ AN", logProb: -0.4, share: 0.716 }]] },
      1,
    );

    expect(message.candidates).toEqual([[{ text: "TÔI LÀ AN", score: "-0.40 · 72%" }]]);
  });

  it("điểm cuối kèm phần hotword và dòng (hotword) cuối nhóm", () => {
    const update = parseNBest(
      encode({
        type: "nbest",
        turn: 1,
        segments: [
          [
            { text: "TÔI LÀ A", log_prob: 2.92, share: 0.98, bonus: 9 },
            { text: "TÔI LÀ AN", log_prob: -1.02, share: 0.02, bonus: 0 },
          ],
        ],
        hotwords: [["NGUYỄN VĂN A", "NGUYỄN VĂN B"]],
      }),
    );
    const message = toChatMessage({ ...caller, nbest: update?.segments ?? null }, 1);

    expect(message.candidates).toEqual([
      [
        { text: "TÔI LÀ A", score: "+2.92 · 98% (hotword +9.0)" },
        { text: "TÔI LÀ AN", score: "-1.02 · 2%" },
        { text: "(hotword): NGUYỄN VĂN A, NGUYỄN VĂN B", score: "" },
      ],
    ]);
  });

  it("chưa có top N thì không có candidates", () => {
    expect(toChatMessage(caller, 1)).not.toHaveProperty("candidates");
  });
});

describe("parseTiming", () => {
  it("đọc độ trễ lượt và hiện dưới câu bot", () => {
    const timing = parseTiming(
      encode({
        type: "timing",
        turn: 3,
        asr_mode: "name",
        partials: 5,
        wait_silence: 1200,
        asr_decode: 200,
        turn_wait: 700,
        engine: 900,
        hotwords: 10,
        tts_first_audio: 490,
        total: 3500,
      }),
    );
    expect(timing).toEqual({
      turn: 3,
      asrMode: "name",
      waitSilence: 1200,
      asrDecode: 200,
      turnWait: 700,
      engine: 900,
      ttsFirstAudio: 490,
      total: 3500,
    });
    if (!timing) throw new Error("timing");
    expect(formatTiming(timing)).toBe(
      "⏱ 3,50s = chờ im lặng 1,20 · ASR tên 0,20 · chốt lượt 0,70 · engine 0,90 · TTS 0,49",
    );
  });

  it("bỏ qua gói khác loại", () => {
    expect(parseTiming(encode({ type: "nbest", turn: 1, segments: [] }))).toBeNull();
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
