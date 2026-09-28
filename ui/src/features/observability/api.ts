import { ApiError, request } from "../../lib/api/client";
import type { TimeWindow } from "./model/range";
import type {
  Aggregation,
  CallDetail,
  ErrorList,
  Overview,
  Quality,
  QualityComponent,
  SlowTurnList,
  TurnExecution,
} from "./model/types";

const BASE = "/internal/observability";

type Params = Record<string, string | number>;

async function get<T>(path: string, window: TimeWindow, params: Params, signal: AbortSignal) {
  const query = new URLSearchParams({ start: window.start, end: window.end });
  for (const [key, value] of Object.entries(params)) query.set(key, String(value));
  try {
    return (await request<T>(`${BASE}${path}?${query.toString()}`, { signal })).data;
  } catch (error) {
    if (error instanceof ApiError) throw new Error(describeError(error), { cause: error });
    throw error;
  }
}

/** Thông điệp cho người xem; không hiện nguyên văn lỗi của server. */
function describeError(error: ApiError): string {
  switch (error.code) {
    case "call_not_found":
      return "Không tìm thấy cuộc gọi trong khoảng thời gian này.";
    case "turn_not_found":
      return "Không tìm thấy lượt trong khoảng thời gian này.";
    case "invalid_time_range":
      return "Khoảng thời gian không hợp lệ.";
    case "observability_unavailable":
      return "Không đọc được dữ liệu trace (thư mục trace lỗi hoặc không truy cập được).";
  }
  if (error.status === 404) {
    return "Observability API chưa bật: đặt OBSERVABILITY_API_ENABLED=true và thư mục trace (TRACE_JSONL_DIR).";
  }
  if (error.status === 0) return "Không kết nối được tới server.";
  return `Không tải được dữ liệu observability (HTTP ${error.status}).`;
}

export const observabilityApi = {
  overview: (window: TimeWindow, slowThresholdMs: number, signal: AbortSignal) =>
    get<Overview>("/overview", window, { slow_threshold_ms: slowThresholdMs }, signal),

  call: (callKey: string, window: TimeWindow, offset: number, limit: number, signal: AbortSignal) =>
    get<CallDetail>(`/calls/${encodeURIComponent(callKey)}`, window, { offset, limit }, signal),

  turn: (traceId: string, window: TimeWindow, signal: AbortSignal) =>
    get<TurnExecution>(`/turns/${encodeURIComponent(traceId)}`, window, {}, signal),

  slowTurns: (
    window: TimeWindow,
    thresholdMs: number,
    offset: number,
    limit: number,
    signal: AbortSignal,
  ) =>
    get<SlowTurnList>("/slow-turns", window, { threshold_ms: thresholdMs, offset, limit }, signal),

  errors: (window: TimeWindow, signal: AbortSignal) =>
    get<ErrorList>("/errors", window, { limit: 25 }, signal),

  quality: (
    window: TimeWindow,
    component: QualityComponent,
    aggregation: Aggregation,
    signal: AbortSignal,
  ) => get<Quality>("/quality", window, { component, aggregation, candidate_limit: 100 }, signal),
};
