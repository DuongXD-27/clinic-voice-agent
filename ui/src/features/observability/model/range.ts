/** Khoảng thời gian xem, tính bằng giờ tính ngược từ lúc bấm Làm mới. */
export const RANGE_OPTIONS = [
  { hours: 1, label: "1 giờ" },
  { hours: 24, label: "24 giờ" },
  { hours: 168, label: "7 ngày" },
] as const;

export type RangeHours = (typeof RANGE_OPTIONS)[number]["hours"];

const DEFAULT_RANGE: RangeHours = 24;

export interface TimeWindow {
  start: string;
  end: string;
}

/** `?range=` trên URL; giá trị lạ về mặc định. */
export function parseRange(value: string | null): RangeHours {
  const hours = Number(value);
  return RANGE_OPTIONS.find((option) => option.hours === hours)?.hours ?? DEFAULT_RANGE;
}

export function toWindow(hours: number, endMs: number): TimeWindow {
  return {
    start: new Date(endMs - hours * 3_600_000).toISOString(),
    end: new Date(endMs).toISOString(),
  };
}
