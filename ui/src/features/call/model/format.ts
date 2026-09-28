import type { DemoDebug } from "../../../lib/api/demoDebug";

/** Dòng phụ dưới câu bot: lượt, trạng thái, nguồn trích xuất, lý do chuyển máy, lỗi, thời gian. */
export function messageMeta(
  turn: number,
  state: string,
  debug: DemoDebug,
  elapsedMs: number,
): string {
  const parts = [`BOT · lượt ${turn}`, state];
  const { extraction, transferReason, errorType, errorCode } = debug;
  if (extraction) {
    const question = extraction.questionId ? ` · ${extraction.questionId}` : "";
    parts.push(`Trích xuất: ${extraction.source} (${extraction.provenance})${question}`);
  }
  if (transferReason) parts.push(`Chuyển máy: ${transferReason}`);
  if (errorType) parts.push(`Lỗi: ${errorType}${errorCode ? ` (${errorCode})` : ""}`);
  parts.push(`${elapsedMs} ms`);
  return parts.join(" · ");
}

export const FIELD_LABELS: Readonly<Record<string, string>> = {
  full_name: "Họ tên",
  dob: "Ngày sinh",
  intent: "Ý định",
  clinical: "Lâm sàng",
  agreement: "Đồng ý",
  slot_choice: "Chọn khung",
  cancel_reason: "Lý do hủy",
  line_signal: "Tín hiệu đường dây",
};

export function formatValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") return String(value);
  return JSON.stringify(value);
}

export interface Segment {
  text: string;
  marked: boolean;
}

/**
 * Chia câu thành đoạn thường / đoạn được trích để tô sáng. So không phân biệt hoa thường;
 * span không tìm thấy hoặc chồng lên span trước thì bỏ qua.
 */
export function highlightSpans(transcript: string, spans: readonly (string | null)[]): Segment[] {
  const lower = transcript.toLowerCase();
  const ranges: [number, number][] = [];
  for (const span of spans) {
    if (!span) continue;
    const start = lower.indexOf(span.toLowerCase());
    const end = start + span.length;
    if (start < 0 || ranges.some(([s, e]) => start < e && end > s)) continue;
    ranges.push([start, end]);
  }
  ranges.sort((a, b) => a[0] - b[0]);

  const segments: Segment[] = [];
  let cursor = 0;
  for (const [start, end] of ranges) {
    if (start > cursor) segments.push({ text: transcript.slice(cursor, start), marked: false });
    segments.push({ text: transcript.slice(start, end), marked: true });
    cursor = end;
  }
  if (cursor < transcript.length) segments.push({ text: transcript.slice(cursor), marked: false });
  return segments;
}

/** Thông báo cho lỗi auth thay vì câu thô của backend. */
export function describeFailure(code: string | null, message: string, hasApiKey: boolean): string {
  if (code === "BAD_KEY") {
    return hasApiKey
      ? "API key không đúng. Kiểm tra lại ô API key."
      : "Bot yêu cầu API key. Điền key vào ô API key rồi thử lại.";
  }
  return message;
}
