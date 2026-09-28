/** Định dạng số liệu observability; null/NaN hiện "—" thay vì 0 để không nhầm với số đo thật. */

const DECIMAL = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 1 });
const INTEGER = new Intl.NumberFormat("vi-VN", { maximumFractionDigits: 0 });
const TIMESTAMP = new Intl.DateTimeFormat("vi-VN", {
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
  second: "2-digit",
});

export const NO_DATA = "—";

function finite(value: number | null | undefined): value is number {
  return value !== null && value !== undefined && Number.isFinite(value);
}

export function formatDuration(ms: number | null | undefined): string {
  if (!finite(ms)) return NO_DATA;
  return ms < 1000 ? `${INTEGER.format(ms)} ms` : `${DECIMAL.format(ms / 1000)} s`;
}

export function formatRate(rate: number | null | undefined): string {
  return finite(rate) ? `${DECIMAL.format(rate * 100)}%` : NO_DATA;
}

export function formatCount(value: number | null | undefined): string {
  return finite(value) ? INTEGER.format(value) : NO_DATA;
}

export function formatTimestamp(value: string | null | undefined): string {
  if (!value) return NO_DATA;
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? NO_DATA : TIMESTAMP.format(parsed);
}

/** Provider/model/mã lỗi trống hiện rõ là chưa ghi nhận. */
export function displayLabel(value: string | null | undefined): string {
  return value?.trim() ? value : "UNSPECIFIED";
}
