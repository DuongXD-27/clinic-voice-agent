export class ObservabilityApiError extends Error {
  constructor(message, { status = 0, code = "network_error" } = {}) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

function configuredBase() {
  const configured = globalThis.OBSERVABILITY_DASHBOARD_CONFIG?.apiBase?.trim();
  if (configured) return configured.replace(/\/$/, "");
  return globalThis.location?.origin || "http://localhost";
}

function friendlyError(status, code) {
  if (code === "call_not_found") return "Call not found";
  if (code === "turn_not_found") return "Turn not found";
  if (status === 404) return "Observability API is not enabled";
  if (status === 422 || code === "invalid_time_range") return "Invalid time range or request";
  if (status === 503) return "Observability data unavailable";
  return "Unable to load observability data";
}

export function createObservabilityClient({ baseUrl = configuredBase(), fetchImpl = fetch } = {}) {
  const request = async (path, params = {}) => {
    const url = new URL(path, `${baseUrl.replace(/\/$/, "")}/`);
    for (const [key, value] of Object.entries(params)) {
      if (value !== null && value !== undefined && value !== "") url.searchParams.set(key, String(value));
    }
    let response;
    try {
      response = await fetchImpl(url.toString(), { headers: { Accept: "application/json" } });
    } catch (cause) {
      throw new ObservabilityApiError("Network error while loading observability data", { code: "network_error", cause });
    }
    let payload = null;
    try {
      payload = await response.json();
    } catch {
      // Error responses are intentionally normalized below; server bodies are never rendered raw.
    }
    if (!response.ok) {
      const code = payload?.detail?.code || `http_${response.status}`;
      throw new ObservabilityApiError(friendlyError(response.status, code), { status: response.status, code });
    }
    return payload;
  };

  const rangeParams = ({ start, end }) => ({ start, end });
  return Object.freeze({
    getOverview: (range, slowThresholdMs = 2000) =>
      request("internal/observability/overview", { ...rangeParams(range), slow_threshold_ms: slowThresholdMs }),
    getCall: (callKey, range, { limit = 50, offset = 0 } = {}) =>
      request(`internal/observability/calls/${encodeURIComponent(callKey)}`, { ...rangeParams(range), limit, offset }),
    getTurn: (traceId, range) =>
      request(`internal/observability/turns/${encodeURIComponent(traceId)}`, rangeParams(range)),
    getSlowTurns: (range, { thresholdMs = 2000, limit = 25, offset = 0 } = {}) =>
      request("internal/observability/slow-turns", { ...rangeParams(range), threshold_ms: thresholdMs, limit, offset }),
    getErrors: (range, { limit = 25 } = {}) =>
      request("internal/observability/errors", { ...rangeParams(range), limit }),
    getQuality: (range, { component = "STT", aggregation = "call", candidateLimit = 100 } = {}) =>
      request("internal/observability/quality", {
        ...rangeParams(range),
        component,
        aggregation,
        candidate_limit: candidateLimit,
      }),
  });
}
