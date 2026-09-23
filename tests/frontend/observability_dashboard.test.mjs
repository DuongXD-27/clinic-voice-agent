import assert from "node:assert/strict";
import test from "node:test";

import { createObservabilityClient, ObservabilityApiError } from "../../src/callbot/transports/http/observability_static/api.mjs";
import {
  renderCallDetail,
  renderHourlyTrend,
  renderOverviewDetail,
  renderOverviewKpis,
  renderProviderModels,
  renderQuality,
  renderSlowTurns,
  renderTopErrors,
  renderTurnDetail,
} from "../../src/callbot/transports/http/observability_static/components.mjs";
import { formatDuration, formatRate } from "../../src/callbot/transports/http/observability_static/format.mjs";
import { normalizeOverviewMetric, toggleOverviewMetric } from "../../src/callbot/transports/http/observability_static/overview_state.mjs";
import { changeQualityState, QUALITY_DEFAULTS } from "../../src/callbot/transports/http/observability_static/quality_state.mjs";

const latency = (count, p50, p95, p99) => ({
  count,
  p50_ms: p50,
  p95_ms: p95,
  p99_ms: p99,
  min_ms: p50,
  max_ms: p99,
  mean_ms: p95,
});

const overview = {
  time_range: { start: "2026-09-20T00:00:00Z", end: "2026-09-21T00:00:00Z" },
  turn_count: 12,
  turn_latency: latency(12, 420, 1180, 1700),
  stt_latency: latency(12, 210, 824, 1100),
  core_latency: latency(12, 300, 520, 760),
  tts_latency: latency(11, 180, 250, 410),
  clinic_latency: latency(2, 80, 95, 100),
  turn_error: { count: 1, denominator: 12, rate: 0.0833 },
  slow_turn: { count: 2, denominator: 12, rate: 0.1667 },
  stt_empty: { empty_count: 1, eligible_count: 12, rate: 0.0833 },
  component_errors: [
    { component: "TURN", count: 12, error_count: 1, error_rate: 0.0833 },
    { component: "STT", count: 12, error_count: 1, error_rate: 0.0833 },
  ],
  provider_model_breakdown: [
    { component: "STT", provider: "asr-safe", model: "asr-v1", count: 12, error_count: 1, error_rate: 0.0833, latency: latency(12, 210, 824, 1100) },
    { component: "TTS", provider: "synthetic-tts", model: "fixture-v1", count: 11, error_count: 0, error_rate: 0, latency: latency(11, 180, 800, 900) },
  ],
  hourly: [
    { start_time: "2026-09-20T22:00:00Z", turn_count: 3, turn_error_count: 0, slow_turn_count: 0, turn_p95_ms: 800, stt_count: 3, stt_p95_ms: 200, core_count: 3, core_p95_ms: 350, tts_count: 3, tts_p95_ms: 180, stt_empty: { empty_count: 0, eligible_count: 3, rate: 0 } },
    { start_time: "2026-09-20T23:00:00Z", turn_count: 0, turn_error_count: 0, slow_turn_count: 0, turn_p95_ms: null, stt_count: 0, stt_p95_ms: null, core_count: 0, core_p95_ms: null, tts_count: 0, tts_p95_ms: null, stt_empty: { empty_count: 0, eligible_count: 0, rate: null } },
    { start_time: "2026-09-21T00:00:00Z", turn_count: 9, turn_error_count: 1, slow_turn_count: 2, turn_p95_ms: 1180, stt_count: 9, stt_p95_ms: 824, core_count: 9, core_p95_ms: 520, tts_count: 8, tts_p95_ms: 250, stt_empty: { empty_count: 1, eligible_count: 9, rate: 0.1111 } },
  ],
  diagnostics: { records_processed: 48, records_skipped: 0, unsupported_records: 0, files_read: 1, files_skipped: 0 },
};

const execution = {
  call_key: "ck_v1_safe_a",
  turn: 2,
  trace_id: "00000000000000000000000000000002",
  start_time: "2026-09-20T23:30:00Z",
  duration_ms: 1180,
  status: "OK",
  replayed: false,
  stages: {
    stt: { component: "STT", operation: "speech.stt.transcribe", duration_ms: 310, provider: "asr-safe", model: "asr-v1", status: "OK", error_code: null },
    core: { component: "CORE", operation: "core.handle_turn", duration_ms: 520, provider: null, model: null, status: "OK", error_code: null },
    tts: { component: "TTS", operation: "speech.tts.synthesize", duration_ms: 800, provider: "synthetic-tts", model: "fixture-v1", status: "OK", error_code: null },
  },
  clinic: [{ component: "CLINIC", operation: "clinic.get_appointment", duration_ms: 95, provider: null, model: null, status: "OK", error_code: null }],
  error_codes: [],
};

const quality = {
  component: "STT",
  aggregation: "call",
  eligible_count: 10,
  affected_count: 2,
  clean_count: 8,
  affected_rate: 0.2,
  issues: [
    { code: "STT_EMPTY_TRANSCRIPT", label: "Transcript rỗng", severity: "Cần xem", affected_count: 2, eligible_count: 8, rate: 0.25 },
    { code: "STT_PROVIDER_ERROR", label: "Lỗi nhà cung cấp STT", severity: "Lỗi", affected_count: 1, eligible_count: 10, rate: 0.1 },
  ],
  coverage: [
    { metric: "Confidence below threshold", instrumentation_status: "NOT_INSTRUMENTED", detail: "Confidence telemetry is not currently available." },
  ],
  candidates: [
    { call_key: execution.call_key, turn: execution.turn, trace_id: execution.trace_id, issue_code: "STT_EMPTY_TRANSCRIPT", issue_label: "Transcript rỗng", safe_value: "transcript_empty=true", status: "OK" },
  ],
};

const ttsQuality = {
  ...quality,
  component: "TTS",
  issues: [],
  coverage: [
    { metric: "TTS TTFA", instrumentation_status: "NOT_INSTRUMENTED", detail: "First-audio telemetry is not currently populated." },
  ],
  candidates: [],
};

const slowTurn = {
  call_key: execution.call_key,
  turn: execution.turn,
  trace_id: execution.trace_id,
  start_time: execution.start_time,
  duration_ms: 2500,
  stt_ms: 310,
  core_ms: 520,
  tts_ms: 250,
  status: "ERROR",
  error_codes: ["SAFE_CODE"],
};

const overviewContext = {
  errorsData: [{ component: "STT", provider: "asr-safe", model: "asr-v1", error_code: "SAFE_CODE", count: 1 }],
  errorsStatus: "ready",
  slowItems: [slowTurn],
  slowStatus: "ready",
  slowThreshold: 2000,
  slowOffset: 0,
  slowHasNext: false,
  emptyData: quality,
  emptyStatus: "ready",
};

test("quality defaults and independent toggle state match PM requirements", () => {
  assert.deepEqual(QUALITY_DEFAULTS, {
    qualityComponent: "stt",
    qualityView: "both",
    qualityAggregation: "call",
  });
  const selected = changeQualityState(QUALITY_DEFAULTS, "qualityView", "charts");
  const switched = changeQualityState(selected, "qualityComponent", "tts");
  const aggregated = changeQualityState(switched, "qualityAggregation", "turn");
  assert.deepEqual(aggregated, {
    qualityComponent: "tts",
    qualityView: "charts",
    qualityAggregation: "turn",
  });
});

test("overview renders backend KPI values without percentile calculation", () => {
  const html = renderOverviewKpis(overview);
  assert.match(html, /Turn p95/);
  assert.match(html, /1\.2 s/);
  assert.match(html, /824 ms/);
  assert.match(html, /1 \/ 12 turns/);
  assert.equal(formatRate(overview.slow_turn.rate), "16.7%");
});

test("overview defaults to compact KPI-only state and excludes unsupported LLM", () => {
  const html = renderOverviewKpis(overview);
  assert.equal(normalizeOverviewMetric(null), null);
  assert.equal(renderOverviewDetail(null, overview, overviewContext), "");
  assert.doesNotMatch(html, /LLM p95/);
  assert.equal(normalizeOverviewMetric("llm"), null);
});

test("overview KPI controls use native keyboard activation and selected semantics", () => {
  const html = renderOverviewKpis(overview, "stt");
  assert.match(html, /<button[^>]+type="button"[^>]+data-overview-metric="stt"[^>]+aria-pressed="true"/);
  assert.match(html, /class="kpi [^"]*selected/);
  assert.match(html, /Đang xem/);
});

test("overview metric reducer opens, replaces, and collapses one contextual detail", () => {
  const turn = toggleOverviewMetric(null, "turn");
  const stt = toggleOverviewMetric(turn, "stt");
  const collapsed = toggleOverviewMetric(stt, "stt");
  assert.equal(turn, "turn");
  assert.equal(stt, "stt");
  assert.equal(collapsed, null);
  assert.match(renderOverviewDetail(turn, overview, overviewContext), /Turn latency/);
  const sttHtml = renderOverviewDetail(stt, overview, overviewContext);
  assert.match(sttHtml, /STT latency/);
  assert.match(sttHtml, /STT provider \/ model/);
  assert.doesNotMatch(sttHtml, /Turn latency/);
});

test("overview error detail combines component health, safe codes, and provider context", () => {
  const html = renderOverviewDetail("error", overview, overviewContext);
  assert.match(html, /Error health/);
  assert.match(html, /Top errors/);
  assert.match(html, /Provider \/ model errors/);
  assert.match(html, /SAFE_CODE/);
});

test("overview component details keep trend, percentiles, and providers focused", () => {
  const coreHtml = renderOverviewDetail("core", overview, overviewContext);
  assert.match(coreHtml, /Core processing latency/);
  assert.doesNotMatch(coreHtml, /CORE provider \/ model/);
  const ttsHtml = renderOverviewDetail("tts", overview, overviewContext);
  assert.match(ttsHtml, /TTS latency/);
  assert.match(ttsHtml, /synthetic-tts/);
  assert.doesNotMatch(ttsHtml, /asr-safe/);
  assert.match(ttsHtml, /data-quality-link="tts"/);
});

test("overview slow-turn detail includes threshold, pagination, and drill-down", () => {
  const html = renderOverviewDetail("slow_turn", overview, overviewContext);
  assert.match(html, /data-slow-threshold/);
  assert.match(html, /data-slow-page="previous"/);
  assert.match(html, /data-call-key="ck_v1_safe_a"/);
  assert.match(html, /data-trace-id="00000000000000000000000000000002"/);
});

test("overview empty-transcript detail shows counts, candidates, and Quality link", () => {
  const html = renderOverviewDetail("empty_transcript", overview, overviewContext);
  assert.match(html, /Affected/);
  assert.match(html, /Eligible/);
  assert.match(html, /8\.3%/);
  assert.match(html, /data-quality-link="stt"/);
  assert.match(html, /data-call-key="ck_v1_safe_a"/);
});

test("null metrics render No data rather than zero", () => {
  assert.equal(formatDuration(null), "No data");
  assert.equal(formatRate(null), "No data");
  const html = renderOverviewKpis({ ...overview, stt_latency: latency(0, null, null, null) });
  assert.match(html, /STT p95[\s\S]*No data[\s\S]*n=0/);
});

test("quality distinguishes available data from not instrumented telemetry", () => {
  const html = renderQuality(quality);
  assert.match(html, /Transcript rỗng/);
  assert.match(html, /25%/);
  assert.match(html, /Confidence below threshold/);
  assert.match(html, /NOT INSTRUMENTED/);
  assert.doesNotMatch(html, /11\.9%/);
});

test("TTS quality leaves first-audio coverage uninstrumented", () => {
  const html = renderQuality(ttsQuality);
  assert.match(html, /TTS TTFA[\s\S]*NOT INSTRUMENTED/);
});

test("quality display modes show numbers, charts, or both", () => {
  const numbers = renderQuality(quality, { view: "numbers" });
  const charts = renderQuality(quality, { view: "charts" });
  const both = renderQuality(quality, { view: "both" });
  assert.match(numbers, /Breakdown theo loại vấn đề/);
  assert.doesNotMatch(numbers, /class="donut"/);
  assert.match(charts, /class="donut"/);
  assert.doesNotMatch(charts, /Breakdown theo loại vấn đề/);
  assert.match(both, /class="donut"/);
  assert.match(both, /Breakdown theo loại vấn đề/);
});

test("quality renders distinct no-data and clean states", () => {
  const noData = renderQuality({ ...quality, eligible_count: 0, affected_count: 0, clean_count: 0, affected_rate: null, issues: quality.issues.map((item) => ({ ...item, affected_count: 0, eligible_count: 0, rate: null })), candidates: [] });
  const clean = renderQuality({ ...quality, affected_count: 0, clean_count: 10, affected_rate: 0, issues: quality.issues.map((item) => ({ ...item, affected_count: 0, rate: 0 })), candidates: [] });
  assert.match(noData, /NO DATA/);
  assert.doesNotMatch(noData, /CLEAN/);
  assert.match(clean, /CLEAN/);
  assert.doesNotMatch(clean, /NO DATA/);
});

test("quality candidates navigate to call and existing turn detail without PII", () => {
  const html = renderQuality(quality, { selectedIssue: "STT_EMPTY_TRANSCRIPT" });
  assert.match(html, /data-call-key="ck_v1_safe_a"/);
  assert.match(html, /data-trace-id="00000000000000000000000000000002"/);
  assert.match(html, /transcript_empty=true/);
  for (const forbidden of ["patient", "phone", "DOB", "utterance", "audio_url"]) assert.doesNotMatch(html, new RegExp(forbidden, "i"));
});

test("provider model table uses API percentiles and error values", () => {
  const html = renderProviderModels(overview.provider_model_breakdown);
  assert.match(html, /asr-safe/);
  assert.match(html, /asr-v1/);
  assert.match(html, /824 ms/);
  assert.match(html, /8\.3%/);
});

test("slow turn table exposes call and trace drill-down actions", () => {
  const html = renderSlowTurns([{ call_key: execution.call_key, turn: 2, trace_id: execution.trace_id, start_time: execution.start_time, duration_ms: 2500, stt_ms: 310, core_ms: 520, tts_ms: 250, status: "ERROR", error_codes: ["SAFE_CODE"] }]);
  assert.match(html, /data-call-key="ck_v1_safe_a"/);
  assert.match(html, /data-trace-id="00000000000000000000000000000002"/);
  assert.match(html, /SAFE_CODE/);
});

test("call detail keeps repeated turn executions and replay marker", () => {
  const replay = { ...execution, trace_id: "00000000000000000000000000000003", replayed: true };
  const html = renderCallDetail({ call_key: execution.call_key, executions: [execution, replay], total_executions: 2, limit: 50, offset: 0 });
  const body = html.match(/<tbody>([\s\S]+)<\/tbody>/)?.[1] || "";
  assert.equal((body.match(/<tr>/g) || []).length, 2);
  assert.match(html, /Replay/);
  assert.match(html, /00000000000000000000000000000002/);
  assert.match(html, /00000000000000000000000000000003/);
});

test("turn detail renders duration-only pipeline and clinic stage", () => {
  const html = renderTurnDetail(execution);
  for (const label of ["TURN", "STT", "CORE", "TTS", "CLINIC"]) assert.match(html, new RegExp(label));
  assert.match(html, /Stage offsets are unavailable/);
  assert.match(html, /not a distributed trace timeline/);
});

test("empty datasets have explicit empty states", () => {
  assert.match(renderHourlyTrend([]), /No hourly data/);
  assert.match(renderTopErrors([]), /No errors/);
  assert.match(renderSlowTurns([]), /No slow turns/);
});

test("API errors are normalized and never expose server body", async () => {
  const client = createObservabilityClient({
    baseUrl: "https://safe.example",
    fetchImpl: async () => ({ ok: false, status: 503, json: async () => ({ detail: { code: "observability_unavailable", message: "sensitive server detail" } }) }),
  });
  await assert.rejects(client.getOverview({ start: "2026-09-20T00:00:00Z", end: "2026-09-21T00:00:00Z" }), (error) => {
    assert.ok(error instanceof ObservabilityApiError);
    assert.equal(error.message, "Observability data unavailable");
    assert.doesNotMatch(error.message, /sensitive/);
    return true;
  });
});

test("API client encodes identifiers and sends timezone-aware range", async () => {
  let requested;
  const client = createObservabilityClient({
    baseUrl: "https://safe.example/base",
    fetchImpl: async (url) => { requested = new URL(url); return { ok: true, status: 200, json: async () => ({}) }; },
  });
  await client.getCall("ck_v1_safe/value", { start: "2026-09-20T00:00:00.000Z", end: "2026-09-21T00:00:00.000Z" });
  assert.match(requested.pathname, /ck_v1_safe%2Fvalue$/);
  assert.equal(requested.searchParams.get("start"), "2026-09-20T00:00:00.000Z");
  assert.equal(requested.searchParams.get("end"), "2026-09-21T00:00:00.000Z");
});

test("quality API client sends closed component and aggregation selections", async () => {
  let requested;
  const client = createObservabilityClient({
    baseUrl: "https://safe.example/base",
    fetchImpl: async (url) => { requested = new URL(url); return { ok: true, status: 200, json: async () => ({}) }; },
  });
  await client.getQuality({ start: "2026-09-20T00:00:00.000Z", end: "2026-09-21T00:00:00.000Z" }, { component: "TTS", aggregation: "turn" });
  assert.match(requested.pathname, /internal\/observability\/quality$/);
  assert.equal(requested.searchParams.get("component"), "TTS");
  assert.equal(requested.searchParams.get("aggregation"), "turn");
});

test("rendered DTO contains only operational identifiers and no canary extras", () => {
  const canary = { ...execution, unrecognized_private_canary: "DO_NOT_RENDER" };
  const html = renderTurnDetail(canary);
  assert.doesNotMatch(html, /DO_NOT_RENDER/);
  assert.match(html, new RegExp(execution.trace_id));
  assert.match(html, /Turn/);
});
