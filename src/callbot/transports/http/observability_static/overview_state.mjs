export const OVERVIEW_METRICS = new Set([
  "turn",
  "stt",
  "core",
  "tts",
  "error",
  "slow_turn",
  "empty_transcript",
]);

export function normalizeOverviewMetric(value) {
  if (!OVERVIEW_METRICS.has(value)) return null;
  return value;
}

export function toggleOverviewMetric(current, requested) {
  const normalized = normalizeOverviewMetric(requested);
  if (normalized === null || normalized === current) return null;
  return normalized;
}
