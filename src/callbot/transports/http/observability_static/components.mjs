import { displayLabel, formatCount, formatDuration, formatRate, formatTimestamp } from "./format.mjs";

export function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function statusBadge(status) {
  const normalized = String(status || "UNKNOWN").toUpperCase();
  const tone = normalized === "OK" ? "ok" : normalized === "ERROR" ? "error" : "";
  return `<span class="status-badge ${tone}">${escapeHtml(normalized)}</span>`;
}

function table(headers, rows, label) {
  return `<div class="table-wrap"><table aria-label="${escapeHtml(label)}"><thead><tr>${headers
    .map((item) => `<th scope="col" class="${item.numeric ? "numeric" : ""}">${escapeHtml(item.label)}</th>`)
    .join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;
}

export function statePanel(kind, title, detail = "") {
  const safeKind = ["loading", "empty", "error", "not-instrumented"].includes(kind) ? kind : "empty";
  return `<div class="state-panel ${safeKind}" role="${kind === "error" ? "alert" : "status"}"><div><strong>${escapeHtml(title)}</strong>${detail ? `<span>${escapeHtml(detail)}</span>` : ""}</div></div>`;
}

function metricCard(metric, label, value, context, hasData, selectedMetric) {
  const selected = metric === selectedMetric;
  return `<button class="kpi ${hasData ? "" : "no-data"} ${selected ? "selected" : ""}" type="button" data-overview-metric="${escapeHtml(metric)}" aria-pressed="${selected}" aria-controls="overview-detail-panel"><span class="kpi-label">${escapeHtml(label)}</span><strong class="kpi-value">${escapeHtml(value)}</strong><span class="kpi-context">${escapeHtml(context)}</span>${selected ? '<span class="kpi-active">Đang xem</span>' : ""}</button>`;
}

export function renderOverviewKpis(data, selectedMetric = null) {
  const latency = [
    ["turn", "Turn p95", data.turn_latency],
    ["stt", "STT p95", data.stt_latency],
    ["core", "Core p95", data.core_latency],
    ["tts", "TTS p95", data.tts_latency],
  ];
  const cards = latency.map(([metric, label, item]) =>
    metricCard(metric, label, formatDuration(item.p95_ms), `n=${formatCount(item.count)}`, item.p95_ms !== null, selectedMetric),
  );
  cards.push(
    metricCard(
      "error",
      "Error rate",
      formatRate(data.turn_error.rate),
      `${formatCount(data.turn_error.count)} / ${formatCount(data.turn_error.denominator)} turns`,
      data.turn_error.rate !== null,
      selectedMetric,
    ),
    metricCard(
      "slow_turn",
      "Slow-turn rate",
      formatRate(data.slow_turn.rate),
      `${formatCount(data.slow_turn.count)} / ${formatCount(data.slow_turn.denominator)} turns`,
      data.slow_turn.rate !== null,
      selectedMetric,
    ),
    metricCard(
      "empty_transcript",
      "Empty transcript",
      formatRate(data.stt_empty.rate),
      `${formatCount(data.stt_empty.empty_count)} / ${formatCount(data.stt_empty.eligible_count)} eligible`,
      data.stt_empty.rate !== null,
      selectedMetric,
    ),
  );
  return cards.join("");
}

export function renderLatencyTable(data, selectedComponents = null) {
  const available = [
    ["TURN", data.turn_latency],
    ["STT", data.stt_latency],
    ["CORE", data.core_latency],
    ["TTS", data.tts_latency],
  ];
  const wanted = selectedComponents ? new Set(selectedComponents.map((item) => item.toUpperCase())) : null;
  const rows = available
    .filter(([component]) => !wanted || wanted.has(component))
    .map(([component, item]) => `<tr><th scope="row">${component}</th><td class="numeric">${formatCount(item.count)}</td><td class="numeric">${formatDuration(item.p50_ms)}</td><td class="numeric">${formatDuration(item.p95_ms)}</td><td class="numeric">${formatDuration(item.p99_ms)}</td></tr>`);
  return table(
    [{ label: "Component" }, { label: "Samples", numeric: true }, { label: "p50", numeric: true }, { label: "p95", numeric: true }, { label: "p99", numeric: true }],
    rows,
    "Latency percentiles from the observability API",
  );
}

const trendSeries = [
  { key: "turn_p95_ms", label: "Turn", color: "#006b54" },
  { key: "stt_p95_ms", label: "STT", color: "#326a8f" },
  { key: "core_p95_ms", label: "Core", color: "#76558f" },
  { key: "tts_p95_ms", label: "TTS", color: "#a35d00" },
];

function chartPoint(index, value, count, maxValue) {
  const x = count <= 1 ? 50 : 50 + (index / (count - 1)) * 930;
  const y = 185 - (Number(value) / maxValue) * 150;
  return { x, y };
}

export function renderHourlyTrend(hourly, { components = null } = {}) {
  if (!hourly.length) return statePanel("empty", "No hourly data", "No completed turns exist in this time range.");
  const wanted = components ? new Set(components.map((item) => item.toUpperCase())) : null;
  const activeSeries = trendSeries.filter((series) => !wanted || wanted.has(series.label.toUpperCase()));
  const values = hourly.flatMap((bucket) => activeSeries.map((series) => bucket[series.key]).filter((value) => value !== null && value !== undefined));
  if (!values.length) return statePanel("empty", "No latency data", "Hourly buckets exist, but percentile values have no samples.");
  const maxValue = Math.max(...values.map(Number), 1);
  const grid = [0, 0.5, 1].map((ratio) => {
    const y = 185 - ratio * 150;
    return `<line class="chart-grid" x1="50" y1="${y}" x2="980" y2="${y}"/><text class="chart-axis" x="45" y="${y + 4}" text-anchor="end">${escapeHtml(formatDuration(maxValue * ratio))}</text>`;
  }).join("");
  const seriesMarkup = activeSeries.map((series) => {
    const segments = [];
    const points = [];
    hourly.forEach((bucket, index) => {
      const value = bucket[series.key];
      if (value === null || value === undefined) return;
      const point = chartPoint(index, value, hourly.length, maxValue);
      points.push(`<circle class="chart-point" cx="${point.x}" cy="${point.y}" r="3.5" fill="${series.color}"><title>${escapeHtml(`${series.label} ${formatDuration(value)} · ${formatTimestamp(bucket.start_time)}`)}</title></circle>`);
      if (index > 0 && hourly[index - 1][series.key] !== null && hourly[index - 1][series.key] !== undefined) {
        const previous = chartPoint(index - 1, hourly[index - 1][series.key], hourly.length, maxValue);
        segments.push(`<line class="chart-line" x1="${previous.x}" y1="${previous.y}" x2="${point.x}" y2="${point.y}" stroke="${series.color}"/>`);
      }
    });
    return segments.join("") + points.join("");
  }).join("");
  const legend = activeSeries.map((series) => `<span class="legend-item"><span class="legend-swatch" style="background:${series.color}"></span>${series.label} p95</span>`).join("");
  const headers = [{ label: "Hour" }, ...activeSeries.map((series) => ({ label: `${series.label} p95`, numeric: true }))];
  const rows = hourly.map((bucket) => `<tr><th scope="row">${escapeHtml(formatTimestamp(bucket.start_time))}</th>${activeSeries.map((series) => `<td class="numeric">${formatDuration(bucket[series.key])}</td>`).join("")}</tr>`);
  return `<div class="chart-wrap"><div class="chart-legend">${legend}</div><svg class="chart" viewBox="0 0 1000 210" role="img" aria-label="Hourly p95 latency trend with gaps for missing values">${grid}${seriesMarkup}</svg></div><details class="chart-table"><summary>Accessible hourly values</summary>${table(headers, rows, "Hourly latency values for the selected component")}</details>`;
}

export function renderComponentErrors(items) {
  if (!items.length) return statePanel("empty", "No component samples", "No error-rate telemetry is available for this range.");
  const rows = items.map((item) => `<tr><th scope="row">${escapeHtml(item.component)}</th><td class="numeric">${formatCount(item.error_count)} / ${formatCount(item.count)}</td><td class="numeric">${formatRate(item.error_rate)}</td></tr>`);
  return table([{ label: "Component" }, { label: "Errors / samples", numeric: true }, { label: "Error rate", numeric: true }], rows, "Component error health");
}

export function renderProviderModels(items) {
  if (!items.length) return statePanel("empty", "No provider/model data", "Provider telemetry has no samples in this range.");
  const rows = items.map((item) => `<tr><th scope="row">${escapeHtml(item.component)}</th><td>${escapeHtml(displayLabel(item.provider))}</td><td>${escapeHtml(displayLabel(item.model))}</td><td class="numeric">${formatCount(item.count)}</td><td class="numeric">${formatDuration(item.latency.p50_ms)}</td><td class="numeric">${formatDuration(item.latency.p95_ms)}</td><td class="numeric">${formatDuration(item.latency.p99_ms)}</td><td class="numeric">${formatCount(item.error_count)}</td><td class="numeric">${formatRate(item.error_rate)}</td></tr>`);
  return table([{ label: "Component" }, { label: "Provider" }, { label: "Model" }, { label: "Count", numeric: true }, { label: "p50", numeric: true }, { label: "p95", numeric: true }, { label: "p99", numeric: true }, { label: "Errors", numeric: true }, { label: "Rate", numeric: true }], rows, "Provider and model performance");
}

export function renderTopErrors(items) {
  if (!items.length) return statePanel("empty", "No errors", "No safe error codes were recorded in this range.");
  const rows = items.map((item) => `<tr><th scope="row">${escapeHtml(item.component)}</th><td>${escapeHtml(displayLabel(item.provider))}</td><td>${escapeHtml(displayLabel(item.model))}</td><td class="error-code">${escapeHtml(displayLabel(item.error_code))}</td><td class="numeric">${formatCount(item.count)}</td></tr>`);
  return table([{ label: "Component" }, { label: "Provider" }, { label: "Model" }, { label: "Error code" }, { label: "Count", numeric: true }], rows, "Top safe error codes");
}

export function renderSlowTurns(items) {
  if (!items.length) return statePanel("empty", "No slow turns", "No turns crossed the selected threshold in this range.");
  const rows = items.map((item) => `<tr><td>${escapeHtml(formatTimestamp(item.start_time))}</td><td><button class="link-button code truncate" type="button" data-call-key="${escapeHtml(item.call_key)}" title="${escapeHtml(item.call_key)}">${escapeHtml(item.call_key)}</button></td><td class="numeric">${formatCount(item.turn)}</td><td class="numeric">${formatDuration(item.duration_ms)}</td><td class="numeric">${formatDuration(item.stt_ms)}</td><td class="numeric">${formatDuration(item.core_ms)}</td><td class="numeric">${formatDuration(item.tts_ms)}</td><td>${statusBadge(item.status)}</td><td class="error-code">${escapeHtml(item.error_codes.join(", ") || "—")}</td><td><button class="link-button" type="button" data-trace-id="${escapeHtml(item.trace_id)}" data-call-key="${escapeHtml(item.call_key)}">View</button></td></tr>`);
  return table([{ label: "Time" }, { label: "Call key" }, { label: "Turn", numeric: true }, { label: "Total", numeric: true }, { label: "STT", numeric: true }, { label: "Core", numeric: true }, { label: "TTS", numeric: true }, { label: "Status" }, { label: "Safe errors" }, { label: "Action" }], rows, "Slow turn executions");
}

function overviewSection(kicker, title, content, action = "") {
  return `<section class="overview-detail-section"><div class="panel-heading"><div><p class="panel-kicker">${escapeHtml(kicker)}</p><h4>${escapeHtml(title)}</h4></div>${action}</div>${content}</section>`;
}

function contextualErrors(context, component) {
  if (context.errorsStatus === "loading") return statePanel("loading", `Loading ${component} errors`);
  if (context.errorsStatus === "error") return statePanel("error", "Error data could not be loaded", "Main KPI values remain available.");
  if (context.errorsStatus !== "ready") return statePanel("loading", `Loading ${component} errors`);
  return renderTopErrors(context.errorsData.filter((item) => item.component === component));
}

function slowTurnDetail(context) {
  const threshold = [1000, 2000, 3000, 5000]
    .map((value) => `<option value="${value}" ${value === context.slowThreshold ? "selected" : ""}>${value / 1000} s</option>`)
    .join("");
  const controls = `<div class="inline-controls"><label for="context-slow-threshold">Threshold</label><select id="context-slow-threshold" data-slow-threshold>${threshold}</select></div>`;
  let body;
  if (context.slowStatus === "loading") body = statePanel("loading", "Loading slow turns");
  else if (context.slowStatus === "error") body = statePanel("error", "Slow turns could not be loaded", "The selected KPI remains available.");
  else if (context.slowStatus === "ready") body = renderSlowTurns(context.slowItems);
  else body = statePanel("loading", "Loading slow turns");
  const start = context.slowItems.length ? context.slowOffset + 1 : 0;
  const pagination = `<div class="pagination" aria-label="Slow turn pagination"><button class="button" type="button" data-slow-page="previous" ${context.slowOffset === 0 || context.slowStatus !== "ready" ? "disabled" : ""}>Previous</button><span>Rows ${start}–${context.slowOffset + context.slowItems.length}</span><button class="button" type="button" data-slow-page="next" ${!context.slowHasNext || context.slowStatus !== "ready" ? "disabled" : ""}>Next</button></div>`;
  return overviewSection("Operations queue", "Slow turns", body + pagination, controls);
}

function emptyTranscriptCandidates(context) {
  if (context.emptyStatus === "loading") return statePanel("loading", "Loading affected calls");
  if (context.emptyStatus === "error") return statePanel("error", "Affected calls could not be loaded", "No transcript content is requested or displayed.");
  if (context.emptyStatus !== "ready") return statePanel("loading", "Loading affected calls");
  const items = context.emptyData.candidates.filter((item) => item.issue_code === "STT_EMPTY_TRANSCRIPT");
  if (!items.length) return statePanel("empty", "No affected calls", "No empty-transcript candidates were recorded in this period.");
  const rows = items.map((item) => `<tr><td><button class="link-button code truncate" type="button" data-call-key="${escapeHtml(item.call_key)}">${escapeHtml(item.call_key)}</button></td><td class="numeric">${formatCount(item.turn)}</td><td>${statusBadge(item.status)}</td><td><button class="link-button" type="button" data-trace-id="${escapeHtml(item.trace_id)}" data-call-key="${escapeHtml(item.call_key)}">View turn</button></td></tr>`);
  return table([{ label: "Call key" }, { label: "Turn", numeric: true }, { label: "Status" }, { label: "Action" }], rows, "Empty transcript affected calls and turns");
}

function latencyOverviewDetail(data, context, component, title, { provider = false, qualityLink = false, slowTurns = false } = {}) {
  const normalized = component.toUpperCase();
  const sections = [
    overviewSection("Hourly", `${normalized} latency trend`, renderHourlyTrend(data.hourly, { components: [normalized] })),
    overviewSection("Distribution", `${normalized} percentiles`, renderLatencyTable(data, [normalized])),
  ];
  if (provider) {
    const rows = data.provider_model_breakdown.filter((item) => item.component === normalized);
    sections.push(overviewSection("Execution mix", `${normalized} provider / model`, renderProviderModels(rows)));
  }
  if (["STT", "CORE", "TTS"].includes(normalized)) {
    sections.push(overviewSection("Safe codes", `${normalized} errors`, contextualErrors(context, normalized)));
  }
  if (slowTurns) sections.push(slowTurnDetail(context));
  if (qualityLink) {
    sections.push(`<button class="link-button overview-quality-link" type="button" data-quality-link="${component.toLowerCase()}">Xem chất lượng ${normalized} →</button>`);
  }
  return `<section class="panel overview-detail" aria-labelledby="overview-detail-heading"><div class="overview-detail-heading"><div><p class="panel-kicker">Contextual detail</p><h3 id="overview-detail-heading" tabindex="-1">${escapeHtml(title)}</h3></div><button class="button button-compact" type="button" data-overview-collapse>Close</button></div>${sections.join("")}</section>`;
}

export function renderOverviewDetail(metric, data, context) {
  if (!metric || !data) return "";
  if (metric === "turn") return latencyOverviewDetail(data, context, "TURN", "Turn latency", { slowTurns: true });
  if (metric === "stt") return latencyOverviewDetail(data, context, "STT", "STT latency", { provider: true, qualityLink: true });
  if (metric === "core") return latencyOverviewDetail(data, context, "CORE", "Core processing latency");
  if (metric === "tts") return latencyOverviewDetail(data, context, "TTS", "TTS latency", { provider: true, qualityLink: true });
  if (metric === "slow_turn") {
    return `<section class="panel overview-detail" aria-labelledby="overview-detail-heading"><div class="overview-detail-heading"><div><p class="panel-kicker">Contextual detail</p><h3 id="overview-detail-heading" tabindex="-1">Slow turns</h3></div><button class="button button-compact" type="button" data-overview-collapse>Close</button></div>${slowTurnDetail(context)}</section>`;
  }
  if (metric === "error") {
    const errors = context.errorsStatus === "ready"
      ? renderTopErrors(context.errorsData)
      : context.errorsStatus === "error"
        ? statePanel("error", "Error details could not be loaded", "The Error rate KPI remains available.")
        : statePanel("loading", "Loading top errors");
    const providerErrors = data.provider_model_breakdown.filter((item) => item.error_count > 0);
    const body = [
      overviewSection("By component", "Error health", renderComponentErrors(data.component_errors)),
      overviewSection("Safe codes", "Top errors", errors),
      overviewSection("Provider context", "Provider / model errors", renderProviderModels(providerErrors)),
    ].join("");
    return `<section class="panel overview-detail" aria-labelledby="overview-detail-heading"><div class="overview-detail-heading"><div><p class="panel-kicker">Contextual detail</p><h3 id="overview-detail-heading" tabindex="-1">Errors</h3></div><button class="button button-compact" type="button" data-overview-collapse>Close</button></div>${body}</section>`;
  }
  if (metric === "empty_transcript") {
    const summary = `<dl class="overview-metric-summary"><div><dt>Affected</dt><dd>${formatCount(data.stt_empty.empty_count)}</dd></div><div><dt>Eligible</dt><dd>${formatCount(data.stt_empty.eligible_count)}</dd></div><div><dt>Rate</dt><dd>${formatRate(data.stt_empty.rate)}</dd></div></dl>`;
    const body = `${summary}${overviewSection("Privacy-safe drill-down", "Affected calls / turns", emptyTranscriptCandidates(context))}<button class="link-button overview-quality-link" type="button" data-quality-link="stt">Xem trong Chất lượng STT →</button>`;
    return `<section class="panel overview-detail" aria-labelledby="overview-detail-heading"><div class="overview-detail-heading"><div><p class="panel-kicker">Contextual detail</p><h3 id="overview-detail-heading" tabindex="-1">Empty transcript</h3></div><button class="button button-compact" type="button" data-overview-collapse>Close</button></div>${body}</section>`;
  }
  return "";
}

function providerSummary(stages) {
  return [stages.stt, stages.tts]
    .filter(Boolean)
    .map((stage) => `${stage.component}: ${displayLabel(stage.provider)} / ${displayLabel(stage.model)}`)
    .join(" · ") || "UNSPECIFIED";
}

export function renderCallDetail(data) {
  const summary = `<dl class="detail-summary"><div><dt>Call pseudonymous ID</dt><dd class="code">${escapeHtml(data.call_key)}</dd></div><div><dt>Execution count</dt><dd>${formatCount(data.total_executions)}</dd></div><div><dt>Page offset</dt><dd>${formatCount(data.offset)}</dd></div></dl>`;
  if (!data.executions.length) return summary + statePanel("empty", "No executions on this page", "Use Previous to return to an earlier page.");
  const rows = data.executions.map((item) => `<tr><td class="numeric">${formatCount(item.turn)}${item.replayed === true ? '<span class="replay-badge">Replay</span>' : ""}</td><td><button class="link-button code truncate" type="button" data-trace-id="${escapeHtml(item.trace_id)}" data-call-key="${escapeHtml(item.call_key)}">${escapeHtml(item.trace_id)}</button></td><td>${escapeHtml(formatTimestamp(item.start_time))}</td><td class="numeric">${formatDuration(item.duration_ms)}</td><td>${statusBadge(item.status)}</td><td class="numeric">${formatDuration(item.stages.stt?.duration_ms)}</td><td class="numeric">${formatDuration(item.stages.core?.duration_ms)}</td><td class="numeric">${formatDuration(item.stages.tts?.duration_ms)}</td><td>${escapeHtml(providerSummary(item.stages))}</td><td><button class="link-button" type="button" data-trace-id="${escapeHtml(item.trace_id)}" data-call-key="${escapeHtml(item.call_key)}">View stages</button></td></tr>`);
  return summary + table([{ label: "Turn", numeric: true }, { label: "Trace ID" }, { label: "Start" }, { label: "Total", numeric: true }, { label: "Status" }, { label: "STT", numeric: true }, { label: "Core", numeric: true }, { label: "TTS", numeric: true }, { label: "Provider / model" }, { label: "Action" }], rows, "Call turn executions including replays");
}

function stageCard(stage) {
  if (!stage) return "";
  return `<article class="stage-card"><h3>${escapeHtml(stage.component)}</h3><dl><dt>Duration</dt><dd>${escapeHtml(formatDuration(stage.duration_ms))}</dd><dt>Status</dt><dd>${statusBadge(stage.status)}</dd><dt>Provider / model</dt><dd>${escapeHtml(displayLabel(stage.provider))} / ${escapeHtml(displayLabel(stage.model))}</dd><dt>Safe error code</dt><dd class="error-code">${escapeHtml(stage.error_code || "—")}</dd></dl></article>`;
}

export function renderTurnDetail(data) {
  const stages = [data.stages.stt, data.stages.core, data.stages.tts, ...data.clinic].filter(Boolean);
  const total = Math.max(Number(data.duration_ms), ...stages.map((stage) => Number(stage.duration_ms)), 1);
  const bars = [
    { component: "TURN", duration_ms: data.duration_ms },
    ...stages,
  ].map((stage) => {
    const width = Math.max(0.3, Math.min(100, (Number(stage.duration_ms) / total) * 100));
    return `<div class="waterfall-row stage-${escapeHtml(stage.component.toLowerCase())}"><strong>${escapeHtml(stage.component)}</strong><div class="waterfall-track" aria-hidden="true"><div class="waterfall-bar" style="width:${width}%"></div></div><span class="numeric">${escapeHtml(formatDuration(stage.duration_ms))}</span></div>`;
  }).join("");
  const summary = `<dl class="detail-summary"><div><dt>Trace ID</dt><dd class="code">${escapeHtml(data.trace_id)}</dd></div><div><dt>Turn</dt><dd>${formatCount(data.turn)}${data.replayed === true ? '<span class="replay-badge">Replay</span>' : ""}</dd></div><div><dt>Total duration</dt><dd>${escapeHtml(formatDuration(data.duration_ms))}</dd></div><div><dt>Status</dt><dd>${statusBadge(data.status)}</dd></div><div><dt>Safe errors</dt><dd class="error-code">${escapeHtml(data.error_codes.join(", ") || "—")}</dd></div></dl>`;
  const cards = stages.map(stageCard).join("");
  return `${summary}<section class="panel"><div class="panel-heading"><div><p class="panel-kicker">Relative durations</p><h3>Execution pipeline</h3></div><span class="muted">Stage offsets are unavailable; positions are not a distributed trace timeline.</span></div><div class="waterfall">${bars}</div></section><div class="stage-cards">${cards || statePanel("empty", "No stage summaries", "This turn has no stage-level telemetry.")}</div>`;
}

function donut(issue, aggregation) {
  const percent = issue.rate === null ? 0 : Math.max(0, Math.min(1, Number(issue.rate))) * 100;
  const unit = aggregation === "call" ? "cuộc gọi" : "lượt";
  const accessible = `${issue.label}: ${formatRate(issue.rate)}, ${formatCount(issue.affected_count)} trên ${formatCount(issue.eligible_count)} ${unit} đủ điều kiện`;
  return `<button class="donut-card" type="button" data-quality-issue="${escapeHtml(issue.code)}" aria-label="Lọc candidate: ${escapeHtml(accessible)}"><svg class="donut" viewBox="0 0 120 120" aria-hidden="true"><circle class="donut-track" cx="60" cy="60" r="48"></circle><circle class="donut-value" cx="60" cy="60" r="48" pathLength="100" stroke-dasharray="${percent} ${100 - percent}" transform="rotate(-90 60 60)"></circle><text x="60" y="65" text-anchor="middle">${escapeHtml(formatRate(issue.rate))}</text></svg><h4>${escapeHtml(issue.label)}</h4><p>${formatCount(issue.affected_count)} / ${formatCount(issue.eligible_count)} ${escapeHtml(unit)}</p></button>`;
}

function qualitySummary(data) {
  const unit = data.aggregation === "call" ? "cuộc gọi" : "lượt";
  const width = data.affected_rate === null ? 0 : Math.max(0, Math.min(1, Number(data.affected_rate))) * 100;
  const subtitle = `${data.aggregation === "call" ? "Cuộc gọi" : "Lượt"} có ít nhất một vấn đề ${data.component}`;
  let state = "";
  if (data.eligible_count === 0) {
    state = statePanel("empty", "NO DATA", `Không có ${unit} ${data.component} đủ điều kiện trong khoảng thời gian này.`);
  } else if (data.affected_count === 0) {
    state = `<div class="clean-message" role="status"><strong>CLEAN</strong><span>Không ghi nhận vấn đề chất lượng ${escapeHtml(data.component)} trong khoảng thời gian này.</span></div>`;
  }
  return `<section class="quality-summary" aria-labelledby="quality-summary-title"><div><p class="panel-kicker">${escapeHtml(subtitle)}</p><h3 id="quality-summary-title">Bao nhiêu ca bị dính?</h3></div><div class="summary-layout"><div class="affected-rate"><strong>${escapeHtml(formatRate(data.affected_rate))}</strong><span>Tỷ lệ bị ảnh hưởng</span></div><div class="summary-counts"><div class="affected-bar" role="img" aria-label="${formatCount(data.affected_count)} bị ảnh hưởng, ${formatCount(data.clean_count)} sạch"><span style="width:${width}%"></span></div><dl><div><dt>Bị ảnh hưởng</dt><dd>${formatCount(data.affected_count)} ${unit}</dd></div><div><dt>Sạch</dt><dd>${formatCount(data.clean_count)} ${unit}</dd></div><div><dt>Tổng đủ điều kiện</dt><dd>${formatCount(data.eligible_count)} ${unit}</dd></div></dl></div></div>${state}</section>`;
}

function issueTable(data) {
  const rows = data.issues.map((issue) => `<tr><th scope="row">${escapeHtml(issue.label)}<span class="issue-code">${escapeHtml(issue.code)}</span></th><td><span class="severity severity-${issue.severity === "Lỗi" ? "error" : "review"}">${escapeHtml(issue.severity)}</span></td><td class="numeric">${formatCount(issue.affected_count)} / ${formatCount(issue.eligible_count)}</td><td class="numeric">${escapeHtml(formatRate(issue.rate))}</td><td><button class="link-button" type="button" data-quality-issue="${escapeHtml(issue.code)}" aria-label="Lọc ví dụ theo ${escapeHtml(issue.label)}">Xem →</button></td></tr>`);
  return `<section class="panel quality-section"><div class="panel-heading"><div><p class="panel-kicker">Số liệu</p><h3>Breakdown theo loại vấn đề</h3></div></div>${table([{ label: "Loại" }, { label: "Mức" }, { label: "Số", numeric: true }, { label: "%", numeric: true }, { label: "" }], rows, `Quality issues for ${data.component}`)}</section>`;
}

function candidateTable(data, selectedIssue) {
  const items = selectedIssue ? data.candidates.filter((item) => item.issue_code === selectedIssue) : data.candidates;
  const selectedLabel = data.issues.find((item) => item.code === selectedIssue)?.label;
  const heading = selectedLabel ? `Ví dụ: ${selectedLabel}` : "Candidate để kiểm tra";
  const clear = selectedIssue ? '<button class="button button-compact" type="button" data-quality-issue="">Bỏ lọc</button>' : "";
  if (!items.length) {
    return `<section class="panel quality-section"><div class="panel-heading"><div><p class="panel-kicker">Drill-down an toàn</p><h3>${escapeHtml(heading)}</h3></div>${clear}</div>${statePanel("empty", "Không có candidate", "Không có execution bị ảnh hưởng cho bộ lọc hiện tại.")}</section>`;
  }
  const rows = items.map((item) => `<tr><td><button class="link-button code truncate" type="button" data-call-key="${escapeHtml(item.call_key)}">${escapeHtml(item.call_key)}</button></td><td class="numeric">${formatCount(item.turn)}</td><td>${escapeHtml(item.issue_label)}<span class="issue-code">${escapeHtml(item.safe_value)}</span></td><td>${statusBadge(item.status)}</td><td><button class="link-button" type="button" data-trace-id="${escapeHtml(item.trace_id)}" data-call-key="${escapeHtml(item.call_key)}">Mở turn →</button></td></tr>`);
  return `<section class="panel quality-section"><div class="panel-heading"><div><p class="panel-kicker">Drill-down an toàn</p><h3>${escapeHtml(heading)}</h3></div>${clear}</div>${table([{ label: "Call key" }, { label: "Turn", numeric: true }, { label: "Vấn đề / safe state" }, { label: "Status" }, { label: "" }], rows, "Privacy-safe affected executions")}</section>`;
}

function coverage(data) {
  const rows = data.coverage.map((item) => {
    return `<li><div><strong>${escapeHtml(item.metric)}</strong><span>${escapeHtml(item.detail)}</span></div><span class="state-chip">${escapeHtml(item.instrumentation_status.replaceAll("_", " "))}</span></li>`;
  }).join("");
  const unavailable = data.coverage.length;
  return `<details class="panel coverage-panel"><summary>Telemetry coverage <span>${formatCount(unavailable)} chưa instrument</span></summary><ul>${rows}</ul></details>`;
}

export function renderQuality(data, { view = "both", selectedIssue = null } = {}) {
  const showCharts = view === "charts" || view === "both";
  const showNumbers = view === "numbers" || view === "both";
  const charts = showCharts ? `<section class="panel quality-section"><div class="panel-heading"><div><p class="panel-kicker">Biểu đồ</p><h3>Tỷ lệ theo loại vấn đề</h3></div></div><div class="donut-grid">${data.issues.map((issue) => donut(issue, data.aggregation)).join("")}</div></section>` : "";
  const numbers = showNumbers ? issueTable(data) : "";
  const note = `<p class="quality-note">Một ${data.aggregation === "call" ? "cuộc gọi" : "lượt"} có thể thuộc nhiều loại vấn đề, nên tổng tỷ lệ theo loại có thể vượt tỷ lệ tổng. Mỗi loại giữ nguyên tập mẫu đủ điều kiện của signal backend.</p>`;
  return `${qualitySummary(data)}${note}${charts}${numbers}${candidateTable(data, selectedIssue)}${coverage(data)}`;
}
