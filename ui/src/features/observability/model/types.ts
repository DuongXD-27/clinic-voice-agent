import type { Schemas } from "../../../lib/api/types";

/** Response của API observability (xem api.ts), sinh từ OpenAPI. */
export type Overview = Schemas["OverviewResponse"];
export type CallDetail = Schemas["CallDetailResponse"];
export type TurnExecution = Schemas["TurnExecutionResponse"];
export type Stage = Schemas["StageResponse"];
export type SlowTurnList = Schemas["SlowTurnListResponse"];
export type ErrorList = Schemas["ErrorListResponse"];
export type Quality = Schemas["QualityResponse"];
export type QualityComponent = "STT" | "TTS";
export type Aggregation = "call" | "turn";
