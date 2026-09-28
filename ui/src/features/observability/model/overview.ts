import type { Overview } from "./types";
import { formatCount, formatDuration, formatRate } from "./format";

/** Thẻ KPI ở trang tổng quan; bấm vào để mở phần chi tiết tương ứng (`?metric=`). */
const METRICS = ["turn", "stt", "core", "tts", "error", "slow_turn", "empty_transcript"] as const;

export type Metric = (typeof METRICS)[number];

/** Thành phần có latency riêng, dùng cho biểu đồ và bảng phân vị. */
export type Component = "TURN" | "STT" | "CORE" | "TTS";

export function parseMetric(value: string | null): Metric | null {
  return METRICS.find((metric) => metric === value) ?? null;
}

export interface KpiCard {
  metric: Metric;
  label: string;
  value: string;
  context: string;
  hasData: boolean;
}

export function kpiCards(data: Overview): KpiCard[] {
  const latency = (metric: Metric, label: string, stats: Overview["turn_latency"]): KpiCard => ({
    metric,
    label,
    value: formatDuration(stats.p95_ms),
    context: `p95 · ${formatCount(stats.count)} mẫu`,
    hasData: stats.p95_ms !== null,
  });
  return [
    latency("turn", "Lượt (end-to-end)", data.turn_latency),
    latency("stt", "STT", data.stt_latency),
    latency("core", "Core", data.core_latency),
    latency("tts", "TTS", data.tts_latency),
    {
      metric: "error",
      label: "Tỷ lệ lỗi",
      value: formatRate(data.turn_error.rate),
      context: `${formatCount(data.turn_error.count)} / ${formatCount(data.turn_error.denominator)} lượt`,
      hasData: data.turn_error.rate !== null,
    },
    {
      metric: "slow_turn",
      label: "Lượt chậm",
      value: formatRate(data.slow_turn.rate),
      context: `${formatCount(data.slow_turn.count)} / ${formatCount(data.slow_turn.denominator)} lượt`,
      hasData: data.slow_turn.rate !== null,
    },
    {
      metric: "empty_transcript",
      label: "Transcript rỗng",
      value: formatRate(data.stt_empty.rate),
      context: `${formatCount(data.stt_empty.empty_count)} / ${formatCount(data.stt_empty.eligible_count)} lượt đủ điều kiện`,
      hasData: data.stt_empty.rate !== null,
    },
  ];
}

export function latencyOf(data: Overview, component: Component): Overview["turn_latency"] {
  switch (component) {
    case "TURN":
      return data.turn_latency;
    case "STT":
      return data.stt_latency;
    case "CORE":
      return data.core_latency;
    case "TTS":
      return data.tts_latency;
  }
}

export const SLOW_THRESHOLDS = [1000, 2000, 3000, 5000] as const;
const DEFAULT_SLOW_THRESHOLD = 2000;

export function parseSlowThreshold(value: string | null): number {
  const threshold = Number(value);
  return SLOW_THRESHOLDS.find((option) => option === threshold) ?? DEFAULT_SLOW_THRESHOLD;
}
