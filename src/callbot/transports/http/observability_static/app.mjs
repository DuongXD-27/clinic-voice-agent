import { createObservabilityClient, ObservabilityApiError } from "./api.mjs";
import {
  renderCallDetail,
  renderOverviewDetail,
  renderOverviewKpis,
  renderQuality,
  renderTurnDetail,
  statePanel,
} from "./components.mjs";
import { formatTimestamp } from "./format.mjs";
import { normalizeOverviewMetric, toggleOverviewMetric } from "./overview_state.mjs";
import { changeQualityState, QUALITY_DEFAULTS } from "./quality_state.mjs";

const client = createObservabilityClient();
const byId = (id) => document.getElementById(id);
const ui = {
  range: byId("range-select"),
  refresh: byId("refresh-button"),
  globalStatus: byId("global-status"),
  windowLabel: byId("window-label"),
  kpis: byId("kpi-panel"),
  overviewHelper: byId("overview-helper"),
  overviewDetail: byId("overview-detail-panel"),
  quality: byId("quality-panel"),
  call: byId("call-panel"),
  callPrev: byId("call-prev"),
  callNext: byId("call-next"),
  callPage: byId("call-page"),
  turn: byId("turn-panel"),
  backToCall: byId("back-to-call"),
};

const state = {
  range: null,
  overview: null,
  selectedOverviewMetric: null,
  errorsData: [],
  errorsStatus: "idle",
  errorsRequest: 0,
  slowItems: [],
  slowStatus: "idle",
  slowRequest: 0,
  slowThreshold: 2000,
  emptyData: null,
  emptyStatus: "idle",
  emptyRequest: 0,
  view: "overview",
  slowOffset: 0,
  slowLimit: 25,
  slowHasNext: false,
  callKey: null,
  callOffset: 0,
  callLimit: 50,
  callTotal: 0,
  traceId: null,
  ...QUALITY_DEFAULTS,
  qualityIssue: null,
  qualityData: null,
  qualityRequest: 0,
  loading: false,
};

function selectedRange() {
  const end = new Date();
  const start = new Date(end.getTime() - Number(ui.range.value) * 60 * 60 * 1000);
  return { start: start.toISOString(), end: end.toISOString() };
}

function errorMarkup(error, fallback) {
  const message = error instanceof ObservabilityApiError ? error.message : fallback;
  return statePanel("error", message, "Retry with Refresh. Server details are intentionally hidden.");
}

function setBusy(busy) {
  state.loading = busy;
  ui.refresh.disabled = busy;
  ui.refresh.textContent = busy ? "Refreshing…" : "Refresh";
  document.querySelector("main").setAttribute("aria-busy", String(busy));
}

function setView(view, { updateUrl = true } = {}) {
  state.view = view;
  document.querySelectorAll(".view").forEach((element) => element.classList.add("hidden"));
  byId(`${view}-view`).classList.remove("hidden");
  document.querySelectorAll(".nav-item").forEach((button) => button.classList.toggle("active", button.dataset.view === view));
  if (updateUrl) {
    const url = new URL(globalThis.location.href);
    url.searchParams.delete("call");
    url.searchParams.delete("trace");
    url.searchParams.delete("screen");
    url.searchParams.delete("component");
    url.searchParams.delete("quality_view");
    url.searchParams.delete("aggregation");
    url.searchParams.delete("metric");
    if (view === "overview" && state.selectedOverviewMetric) {
      url.searchParams.set("metric", state.selectedOverviewMetric);
    }
    if (view === "quality") {
      url.searchParams.set("screen", "quality");
      url.searchParams.set("component", state.qualityComponent);
      url.searchParams.set("quality_view", state.qualityView);
      url.searchParams.set("aggregation", state.qualityAggregation);
    }
    if (view === "call" && state.callKey) url.searchParams.set("call", state.callKey);
    if (view === "turn" && state.traceId) {
      if (state.callKey) url.searchParams.set("call", state.callKey);
      url.searchParams.set("trace", state.traceId);
    }
    history.replaceState(null, "", url);
  }
  byId(`${view}-heading`)?.focus?.({ preventScroll: true });
}

function updateQualityControls() {
  const groups = [
    ["qualityComponent", "quality-component"],
    ["qualityView", "quality-view"],
    ["qualityAggregation", "quality-aggregation"],
  ];
  for (const [stateKey, attribute] of groups) {
    document.querySelectorAll(`[data-${attribute}]`).forEach((button) => {
      const active = button.dataset[attribute.replace(/-([a-z])/g, (_match, letter) => letter.toUpperCase())] === state[stateKey];
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", String(active));
    });
  }
}

function updateQualityUrl() {
  if (state.view !== "quality") return;
  const url = new URL(globalThis.location.href);
  url.searchParams.set("screen", "quality");
  url.searchParams.set("component", state.qualityComponent);
  url.searchParams.set("quality_view", state.qualityView);
  url.searchParams.set("aggregation", state.qualityAggregation);
  history.replaceState(null, "", url);
}

function renderCurrentQuality() {
  if (!state.qualityData) return;
  ui.quality.innerHTML = renderQuality(state.qualityData, {
    view: state.qualityView,
    selectedIssue: state.qualityIssue,
  });
}

function overviewContext() {
  return {
    errorsData: state.errorsData,
    errorsStatus: state.errorsStatus,
    slowItems: state.slowItems,
    slowStatus: state.slowStatus,
    slowThreshold: state.slowThreshold,
    slowOffset: state.slowOffset,
    slowHasNext: state.slowHasNext,
    emptyData: state.emptyData,
    emptyStatus: state.emptyStatus,
  };
}

function renderCurrentOverview() {
  if (!state.overview) return;
  ui.kpis.innerHTML = renderOverviewKpis(state.overview, state.selectedOverviewMetric);
  ui.overviewHelper.classList.toggle("hidden", state.selectedOverviewMetric !== null);
  ui.overviewDetail.innerHTML = renderOverviewDetail(state.selectedOverviewMetric, state.overview, overviewContext());
}

function updateOverviewUrl({ push = false } = {}) {
  if (state.view !== "overview") return;
  const url = new URL(globalThis.location.href);
  url.searchParams.delete("call");
  url.searchParams.delete("trace");
  url.searchParams.delete("screen");
  url.searchParams.delete("metric");
  if (state.selectedOverviewMetric) url.searchParams.set("metric", state.selectedOverviewMetric);
  history[push ? "pushState" : "replaceState"](null, "", url);
}

function setOverviewMetric(metric, { updateUrl = true, push = false, focus = false } = {}) {
  state.selectedOverviewMetric = normalizeOverviewMetric(metric);
  renderCurrentOverview();
  if (updateUrl) updateOverviewUrl({ push });
  ensureOverviewDetailData();
  if (focus && state.selectedOverviewMetric) {
    requestAnimationFrame(() => byId("overview-detail-heading")?.focus({ preventScroll: true }));
  }
}

async function loadQuality() {
  if (!state.range) return;
  const requestId = ++state.qualityRequest;
  ui.quality.innerHTML = statePanel("loading", `Loading ${state.qualityComponent.toUpperCase()} quality`);
  try {
    const data = await client.getQuality(state.range, {
      component: state.qualityComponent.toUpperCase(),
      aggregation: state.qualityAggregation,
    });
    if (requestId !== state.qualityRequest) return;
    state.qualityData = data;
    state.qualityIssue = null;
    renderCurrentQuality();
  } catch (error) {
    if (requestId !== state.qualityRequest) return;
    state.qualityData = null;
    ui.quality.innerHTML = errorMarkup(error, "Quality data could not be loaded");
  }
}

function enableDetailNav() {
  document.querySelector('.nav-item[data-view="call"]').disabled = !state.callKey;
  document.querySelector('.nav-item[data-view="turn"]').disabled = !state.traceId;
}

async function loadSlowTurns() {
  const requestId = ++state.slowRequest;
  state.slowStatus = "loading";
  state.slowItems = [];
  renderCurrentOverview();
  try {
    const result = await client.getSlowTurns(state.range, {
      thresholdMs: state.slowThreshold,
      limit: state.slowLimit,
      offset: state.slowOffset,
    });
    if (requestId !== state.slowRequest) return;
    state.slowItems = result.items;
    state.slowHasNext = result.items.length === state.slowLimit;
    state.slowStatus = "ready";
  } catch (error) {
    if (requestId !== state.slowRequest) return;
    state.slowStatus = "error";
    state.slowItems = [];
  }
  renderCurrentOverview();
}

async function loadErrors() {
  const requestId = ++state.errorsRequest;
  state.errorsStatus = "loading";
  renderCurrentOverview();
  try {
    const result = await client.getErrors(state.range);
    if (requestId !== state.errorsRequest) return;
    state.errorsData = result.items;
    state.errorsStatus = "ready";
  } catch (error) {
    if (requestId !== state.errorsRequest) return;
    state.errorsData = [];
    state.errorsStatus = "error";
  }
  renderCurrentOverview();
}

async function loadEmptyTranscriptCandidates() {
  const requestId = ++state.emptyRequest;
  state.emptyStatus = "loading";
  renderCurrentOverview();
  try {
    const result = await client.getQuality(state.range, { component: "STT", aggregation: "call" });
    if (requestId !== state.emptyRequest) return;
    state.emptyData = result;
    state.emptyStatus = "ready";
  } catch (error) {
    if (requestId !== state.emptyRequest) return;
    state.emptyData = null;
    state.emptyStatus = "error";
  }
  renderCurrentOverview();
}

function ensureOverviewDetailData() {
  const metric = state.selectedOverviewMetric;
  if (["stt", "core", "tts", "error"].includes(metric) && state.errorsStatus === "idle") loadErrors();
  if (["turn", "slow_turn"].includes(metric) && state.slowStatus === "idle") loadSlowTurns();
  if (metric === "empty_transcript" && state.emptyStatus === "idle") loadEmptyTranscriptCandidates();
}

async function loadOverview() {
  state.range = selectedRange();
  const hours = Number(ui.range.value);
  ui.windowLabel.textContent = hours === 1 ? "Last hour" : hours === 24 ? "Last 24 hours" : "Last 7 days";
  ui.kpis.innerHTML = statePanel("loading", "Loading overview");
  ui.overviewDetail.innerHTML = "";
  ui.overviewHelper.classList.remove("hidden");
  state.errorsRequest += 1;
  state.slowRequest += 1;
  state.emptyRequest += 1;
  state.errorsStatus = "idle";
  state.errorsData = [];
  state.slowStatus = "idle";
  state.slowItems = [];
  state.slowHasNext = false;
  state.emptyStatus = "idle";
  state.emptyData = null;
  setBusy(true);
  const overviewPromise = client.getOverview(state.range, state.slowThreshold);
  const [overviewResult] = await Promise.allSettled([overviewPromise]);
  if (overviewResult.status === "fulfilled") {
    const data = overviewResult.value;
    state.overview = data;
    state.selectedOverviewMetric = normalizeOverviewMetric(state.selectedOverviewMetric);
    renderCurrentOverview();
    ensureOverviewDetailData();
    ui.globalStatus.textContent = `Updated ${formatTimestamp(new Date().toISOString())} · ${data.diagnostics.records_processed} records processed`;
  } else {
    state.overview = null;
    const markup = errorMarkup(overviewResult.reason, "Unable to load overview");
    ui.kpis.innerHTML = markup;
    ui.overviewDetail.innerHTML = "";
    ui.globalStatus.textContent = "Dashboard update failed";
  }
  setBusy(false);
}

async function loadCall(callKey, { resetOffset = true } = {}) {
  state.callKey = callKey;
  if (resetOffset) state.callOffset = 0;
  state.traceId = null;
  enableDetailNav();
  setView("call");
  ui.call.innerHTML = statePanel("loading", "Loading call executions");
  ui.callPrev.disabled = true;
  ui.callNext.disabled = true;
  try {
    const result = await client.getCall(callKey, state.range, { limit: state.callLimit, offset: state.callOffset });
    state.callTotal = result.total_executions;
    ui.call.innerHTML = renderCallDetail(result);
    ui.callPrev.disabled = state.callOffset === 0;
    ui.callNext.disabled = state.callOffset + result.executions.length >= result.total_executions;
    const start = result.executions.length ? state.callOffset + 1 : 0;
    ui.callPage.textContent = `Executions ${start}–${state.callOffset + result.executions.length} of ${result.total_executions}`;
  } catch (error) {
    ui.call.innerHTML = errorMarkup(error, "Unable to load call");
    ui.callPage.textContent = "Unavailable";
  }
}

async function loadTurn(traceId, callKey = state.callKey) {
  state.traceId = traceId;
  if (callKey) state.callKey = callKey;
  enableDetailNav();
  setView("turn");
  ui.turn.innerHTML = statePanel("loading", "Loading turn stages");
  try {
    const result = await client.getTurn(traceId, state.range);
    ui.turn.innerHTML = renderTurnDetail(result);
  } catch (error) {
    ui.turn.innerHTML = errorMarkup(error, "Unable to load turn");
  }
}

async function refreshAll() {
  await loadOverview();
  if (state.view === "quality") await loadQuality();
  if (state.view === "call" && state.callKey) await loadCall(state.callKey, { resetOffset: false });
  if (state.view === "turn" && state.traceId) await loadTurn(state.traceId);
}

document.addEventListener("click", (event) => {
  const metricButton = event.target.closest("[data-overview-metric]");
  if (metricButton) {
    const next = toggleOverviewMetric(state.selectedOverviewMetric, metricButton.dataset.overviewMetric);
    setOverviewMetric(next, { push: true, focus: Boolean(next) });
    return;
  }
  if (event.target.closest("[data-overview-collapse]")) {
    setOverviewMetric(null, { push: true });
    return;
  }
  const qualityLink = event.target.closest("[data-quality-link]");
  if (qualityLink) {
    Object.assign(state, changeQualityState(state, "qualityComponent", qualityLink.dataset.qualityLink));
    state.qualityIssue = null;
    updateQualityControls();
    setView("quality");
    loadQuality();
    return;
  }
  const slowPage = event.target.closest("[data-slow-page]");
  if (slowPage) {
    state.slowOffset = slowPage.dataset.slowPage === "previous"
      ? Math.max(0, state.slowOffset - state.slowLimit)
      : state.slowOffset + state.slowLimit;
    loadSlowTurns();
    return;
  }
  const qualityIssueButton = event.target.closest("[data-quality-issue]");
  if (qualityIssueButton) {
    state.qualityIssue = qualityIssueButton.dataset.qualityIssue || null;
    renderCurrentQuality();
    return;
  }
  const componentButton = event.target.closest("[data-quality-component]");
  if (componentButton) {
    Object.assign(state, changeQualityState(state, "qualityComponent", componentButton.dataset.qualityComponent));
    state.qualityIssue = null;
    updateQualityControls();
    updateQualityUrl();
    loadQuality();
    return;
  }
  const qualityViewButton = event.target.closest("[data-quality-view]");
  if (qualityViewButton) {
    Object.assign(state, changeQualityState(state, "qualityView", qualityViewButton.dataset.qualityView));
    updateQualityControls();
    updateQualityUrl();
    renderCurrentQuality();
    return;
  }
  const aggregationButton = event.target.closest("[data-quality-aggregation]");
  if (aggregationButton) {
    Object.assign(state, changeQualityState(state, "qualityAggregation", aggregationButton.dataset.qualityAggregation));
    state.qualityIssue = null;
    updateQualityControls();
    updateQualityUrl();
    loadQuality();
    return;
  }
  const traceButton = event.target.closest("[data-trace-id]");
  if (traceButton) {
    loadTurn(traceButton.dataset.traceId, traceButton.dataset.callKey);
    return;
  }
  const callButton = event.target.closest("[data-call-key]");
  if (callButton) {
    loadCall(callButton.dataset.callKey);
    return;
  }
  const viewButton = event.target.closest("[data-view]");
  if (viewButton && !viewButton.disabled) {
    setView(viewButton.dataset.view);
    if (viewButton.dataset.view === "quality" && !state.qualityData) loadQuality();
  }
});

document.addEventListener("change", (event) => {
  const threshold = event.target.closest("[data-slow-threshold]");
  if (!threshold) return;
  state.slowThreshold = Number(threshold.value);
  state.slowOffset = 0;
  state.slowStatus = "idle";
  refreshAll();
});

ui.refresh.addEventListener("click", refreshAll);
ui.range.addEventListener("change", () => {
  state.slowOffset = 0;
  refreshAll();
});
ui.callPrev.addEventListener("click", () => {
  state.callOffset = Math.max(0, state.callOffset - state.callLimit);
  loadCall(state.callKey, { resetOffset: false });
});
ui.callNext.addEventListener("click", () => {
  state.callOffset += state.callLimit;
  loadCall(state.callKey, { resetOffset: false });
});
ui.backToCall.addEventListener("click", () => {
  if (state.callKey) loadCall(state.callKey, { resetOffset: false });
  else setView("overview");
});

const initial = new URL(globalThis.location.href).searchParams;
const initialCall = initial.get("call");
const initialTrace = initial.get("trace");
state.selectedOverviewMetric = initial.get("metric");
Object.assign(state, changeQualityState(state, "qualityComponent", initial.get("component")));
Object.assign(state, changeQualityState(state, "qualityView", initial.get("quality_view")));
Object.assign(state, changeQualityState(state, "qualityAggregation", initial.get("aggregation")));
updateQualityControls();
await loadOverview();
if (initialTrace) await loadTurn(initialTrace, initialCall);
else if (initialCall) await loadCall(initialCall);
else if (initial.get("screen") === "quality") {
  setView("quality");
  await loadQuality();
}

globalThis.addEventListener("popstate", () => {
  const params = new URL(globalThis.location.href).searchParams;
  if (params.get("call") || params.get("trace") || params.get("screen") === "quality") return;
  setView("overview", { updateUrl: false });
  setOverviewMetric(params.get("metric"), { updateUrl: false });
});
