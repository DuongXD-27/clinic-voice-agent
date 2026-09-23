export const QUALITY_DEFAULTS = Object.freeze({
  qualityComponent: "stt",
  qualityView: "both",
  qualityAggregation: "call",
});

const allowed = Object.freeze({
  qualityComponent: new Set(["stt", "tts"]),
  qualityView: new Set(["numbers", "charts", "both"]),
  qualityAggregation: new Set(["call", "turn"]),
});

export function changeQualityState(current, key, value) {
  if (!allowed[key]?.has(value)) return { ...current };
  return { ...current, [key]: value };
}
