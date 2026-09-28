import { describe, expect, it } from "vitest";

/**
 * Cam kết của dashboard (chuyển từ tests/observability/test_dashboard_frontend.py cũ): chỉ đọc
 * API tổng hợp đã ẩn danh, không đụng dữ liệu bệnh nhân, nội dung hội thoại hay trace thô.
 */
const sources = import.meta.glob<string>(
  ["./**/*.{ts,tsx}", "!./**/*.test.{ts,tsx}", "!./test/**"],
  { query: "?raw", import: "default", eager: true },
);

describe("observability privacy", () => {
  it("quét được mã nguồn của mục observability", () => {
    expect(Object.keys(sources).length).toBeGreaterThan(10);
  });

  it("chỉ api.ts gọi /internal/observability", () => {
    const callers = Object.entries(sources)
      .filter(([, source]) => source.includes("/internal/observability"))
      .map(([path]) => path);

    expect(callers).toEqual(["./api.ts"]);
  });

  it.each([
    "patient_id",
    "appointment_id",
    "utterance",
    "audio_url",
    "langfuse",
    ".jsonl",
    "http://",
    "https://",
  ])("không chứa %s", (literal) => {
    const offenders = Object.entries(sources)
      .filter(([, source]) => source.toLowerCase().includes(literal))
      .map(([path]) => path);

    expect(offenders).toEqual([]);
  });
});
