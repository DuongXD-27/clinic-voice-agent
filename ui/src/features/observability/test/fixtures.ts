/** Dữ liệu mẫu đúng schema OpenAPI cho test observability. */
import type { CallDetail, Overview, Quality, Stage, TurnExecution } from "../model/types";

const latency = (p95: number | null, count = 10): Overview["turn_latency"] => ({
  count,
  p50_ms: p95 === null ? null : p95 / 2,
  p95_ms: p95,
  p99_ms: p95 === null ? null : p95 * 1.2,
  min_ms: p95 === null ? null : 10,
  max_ms: p95 === null ? null : p95 * 1.5,
  mean_ms: p95 === null ? null : p95 / 1.5,
});

export const overview: Overview = {
  time_range: { start: "2026-09-24T00:00:00Z", end: "2026-09-25T00:00:00Z" },
  turn_count: 42,
  turn_latency: latency(2400),
  stt_latency: latency(800),
  core_latency: latency(300),
  tts_latency: latency(1200),
  clinic_latency: latency(150),
  turn_error: { count: 2, denominator: 42, rate: 2 / 42 },
  slow_turn: { count: 5, denominator: 42, rate: 5 / 42 },
  stt_empty: { empty_count: 1, eligible_count: 20, rate: 0.05 },
  component_errors: [{ component: "STT", count: 20, error_count: 1, error_rate: 0.05 }],
  provider_model_breakdown: [
    {
      component: "STT",
      provider: "zipformer",
      model: "gipformer1.5",
      count: 20,
      error_count: 1,
      error_rate: 0.05,
      latency: latency(800),
    },
    {
      component: "TTS",
      provider: "vbee",
      model: "hn_female",
      count: 20,
      error_count: 0,
      error_rate: 0,
      latency: latency(1200),
    },
  ],
  hourly: [
    {
      start_time: "2026-09-24T10:00:00Z",
      turn_count: 20,
      turn_error_count: 1,
      slow_turn_count: 2,
      turn_p95_ms: 2200,
      stt_count: 10,
      stt_p95_ms: 700,
      core_count: 20,
      core_p95_ms: 280,
      tts_count: 10,
      tts_p95_ms: 1100,
      stt_empty: { empty_count: 0, eligible_count: 10, rate: 0 },
    },
    {
      start_time: "2026-09-24T11:00:00Z",
      turn_count: 22,
      turn_error_count: 1,
      slow_turn_count: 3,
      turn_p95_ms: 2600,
      stt_count: 10,
      stt_p95_ms: null,
      core_count: 22,
      core_p95_ms: 320,
      tts_count: 10,
      tts_p95_ms: 1300,
      stt_empty: { empty_count: 1, eligible_count: 10, rate: 0.1 },
    },
  ],
  diagnostics: {
    records_processed: 180,
    records_skipped: 0,
    unsupported_records: 0,
    files_read: 2,
    files_skipped: 0,
  },
};

const stage = (component: string, duration: number, extra: Partial<Stage> = {}): Stage => ({
  component,
  operation: `${component.toLowerCase()}.run`,
  duration_ms: duration,
  provider: null,
  model: null,
  status: "OK",
  error_code: null,
  ...extra,
});

export const turn: TurnExecution = {
  call_key: "call_abc",
  turn: 2,
  trace_id: "trace_123",
  start_time: "2026-09-24T10:05:00Z",
  duration_ms: 2400,
  status: "OK",
  replayed: false,
  stages: {
    stt: stage("STT", 800, { provider: "zipformer", model: "gipformer1.5" }),
    core: stage("CORE", 300),
    tts: stage("TTS", 1200, { provider: "vbee", model: "hn_female" }),
  },
  clinic: [stage("CLINIC", 150, { status: "ERROR", error_code: "SLOT_TAKEN" })],
  error_codes: ["SLOT_TAKEN"],
};

export const callDetail: CallDetail = {
  call_key: "call_abc",
  executions: [turn, { ...turn, turn: 2, trace_id: "trace_124", replayed: true }],
  total_executions: 2,
  limit: 50,
  offset: 0,
};

export const quality: Quality = {
  component: "STT",
  aggregation: "call",
  eligible_count: 20,
  affected_count: 2,
  clean_count: 18,
  affected_rate: 0.1,
  issues: [
    {
      code: "STT_EMPTY_TRANSCRIPT",
      label: "Transcript rỗng",
      severity: "Lỗi",
      affected_count: 1,
      eligible_count: 20,
      rate: 0.05,
    },
    {
      code: "STT_LOW_CONFIDENCE",
      label: "Độ tin cậy thấp",
      severity: "Cần xem",
      affected_count: 1,
      eligible_count: 20,
      rate: 0.05,
    },
  ],
  coverage: [
    { metric: "WER", instrumentation_status: "NOT_INSTRUMENTED", detail: "Cần transcript chuẩn" },
  ],
  candidates: [
    {
      call_key: "call_abc",
      turn: 1,
      trace_id: "trace_empty",
      issue_code: "STT_EMPTY_TRANSCRIPT",
      issue_label: "Transcript rỗng",
      safe_value: "empty",
      status: "OK",
    },
    {
      call_key: "call_def",
      turn: 3,
      trace_id: "trace_low",
      issue_code: "STT_LOW_CONFIDENCE",
      issue_label: "Độ tin cậy thấp",
      safe_value: "0.31",
      status: "OK",
    },
  ],
};
