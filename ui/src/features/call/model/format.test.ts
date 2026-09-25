import { describe, expect, it } from "vitest";

import { readDemoDebug } from "../../../lib/api/demoDebug";
import { describeFailure, formatValue, highlightSpans, messageMeta } from "./format";

describe("highlightSpans", () => {
  it("tô sáng span không phân biệt hoa thường, giữ chữ gốc", () => {
    expect(highlightSpans("Tôi là Nguyễn Văn A", ["nguyễn văn a"])).toEqual([
      { text: "Tôi là ", marked: false },
      { text: "Nguyễn Văn A", marked: true },
    ]);
  });

  it("sắp theo vị trí, bỏ span không có hoặc chồng lấn", () => {
    const segments = highlightSpans("sinh 14/03/1978, tên An", [
      "An",
      "14/03/1978",
      "03",
      null,
      "xyz",
    ]);

    expect(segments).toEqual([
      { text: "sinh ", marked: false },
      { text: "14/03/1978", marked: true },
      { text: ", tên ", marked: false },
      { text: "An", marked: true },
    ]);
  });

  it("không span thì trả nguyên câu", () => {
    expect(highlightSpans("alo", [])).toEqual([{ text: "alo", marked: false }]);
  });
});

describe("messageMeta", () => {
  it("ghép lượt, state, trích xuất, chuyển máy, lỗi và thời gian", () => {
    const debug = readDemoDebug(
      new Headers({
        "X-Demo-Extraction-Source": "LLM",
        "X-Demo-Extraction-Provenance": "FALLBACK",
        "X-Demo-Extraction-Question-Id": "ASK_NAME",
        "X-Demo-Transfer-Reason": "NOT_UNDERSTOOD",
        "X-Demo-Error-Type": "UPSTREAM",
        "X-Demo-Error-Code": "TIMEOUT",
      }),
    );

    expect(messageMeta(2, "ENDED", debug, 340)).toBe(
      "BOT · lượt 2 · ENDED · Trích xuất: LLM (FALLBACK) · ASK_NAME · Chuyển máy: NOT_UNDERSTOOD · Lỗi: UPSTREAM (TIMEOUT) · 340 ms",
    );
  });

  it("bỏ phần không có", () => {
    expect(messageMeta(0, "AWAITING_IDENTITY", readDemoDebug(null), 12)).toBe(
      "BOT · lượt 0 · AWAITING_IDENTITY · 12 ms",
    );
  });
});

describe("formatValue", () => {
  it.each([
    [null, "—"],
    [undefined, "—"],
    ["AGREE", "AGREE"],
    [3, "3"],
    [true, "true"],
    [{ day: 14 }, '{"day":14}'],
  ])("%s → %s", (value, expected) => {
    expect(formatValue(value)).toBe(expected);
  });
});

describe("describeFailure", () => {
  it("hướng dẫn điền key khi thiếu, kiểm tra lại khi sai", () => {
    expect(describeFailure("BAD_KEY", "Missing bearer token.", false)).toContain("yêu cầu API key");
    expect(describeFailure("BAD_KEY", "Invalid bearer token.", true)).toContain("không đúng");
  });

  it("giữ nguyên thông báo của backend cho lỗi khác", () => {
    expect(describeFailure("CALL_NOT_FOUND", "Không tìm thấy cuộc gọi", true)).toBe(
      "Không tìm thấy cuộc gọi",
    );
  });
});
