import type { Schemas } from "../../../lib/api/types";

/** Response của API observability (xem api.ts), sinh từ OpenAPI. */
export interface ExtendedMetrics {
  evaluation: {
    score_count: number;
    by_name: Record<string, number>;
    local_only_count?: number;
  };
  call_count: number;
  turn_count: number;
  trace_count: number;
  turn_latency_p90_ms: number | null;
  technical_errors: { by_component: Record<string, number>; by_code: Record<string, number> };
  llm_latency: { count: number; p50_ms: number | null; p95_ms: number | null };
  llm_model_call_latency?: { count: number; p50_ms: number | null; p95_ms: number | null };
  ttfa: { count: number; p50_ms: number | null; p95_ms: number | null };
  stt_first_partial?: { count: number; p50_ms: number | null; p95_ms: number | null };
  stt_final_latency?: { count: number; p50_ms: number | null; p95_ms: number | null };
  stt_provider_latency?: { count: number; p50_ms: number | null; p95_ms: number | null };
  models: {
    provider: string;
    model: string;
    calls: number;
    ok: number;
    timeout: number;
    error: number;
    invalid: number;
    input_tokens: number;
    output_tokens: number;
  }[];
  stt: {
    count: number;
    confidence_mean: number | null;
    audio_duration_ms: number;
    error_count: number;
    error_rate: number | null;
  };
  tts: {
    count: number;
    characters: number;
    fallback_count: number;
    interrupted_count: number;
    providers: { provider: string; voice: string; count: number }[];
  };
  clinic: {
    operations: Record<string, number>;
    retry_count: number;
    version_conflicts: number;
    error_count: number;
  };
  cost: {
    known_cost_total: number;
    cost_known?: boolean;
    cost_complete: boolean;
    known_component_count: number;
    unknown_component_count: number;
    sessions: {
      call_key: string;
      llm_cost: number;
      tts_cost: number;
      stt_cost: number;
      known_cost_total: number;
      cost_known: boolean;
      cost_complete: boolean;
    }[];
  };
}
export type Overview = Schemas["OverviewResponse"] & { extended?: ExtendedMetrics | null };
export type CallDetail = Schemas["CallDetailResponse"];
export type TurnExecution = Schemas["TurnExecutionResponse"];
export type Stage = Schemas["StageResponse"];
export type SlowTurnList = Schemas["SlowTurnListResponse"];
export type ErrorList = Schemas["ErrorListResponse"];
export type Quality = Schemas["QualityResponse"];
export type QualityComponent = "STT" | "TTS";
export type Aggregation = "call" | "turn";
