/**
 * Trạng thái một cuộc gọi thử, dạng reducer thuần:
 *
 *   idle ─start─▶ starting ─started─▶ active ─turnSent─▶ sending ─turnDone─▶ active | ended
 *                    └─failed─▶ idle                        └─failed─▶ active
 *   (mọi pha) ─reset─▶ idle
 *
 * Action không hợp lệ ở pha hiện tại bị bỏ qua (trả nguyên state), nên double-click hay
 * response đến muộn sau "Phiên mới" không làm hỏng cuộc gọi.
 */
import type { DemoDebug, TurnExtraction } from "../../../lib/api/demoDebug";
import type { Schemas } from "../../../lib/api/types";
import { messageMeta } from "./format";

// Component (ExtractionPanel) không import lib/api: lấy type trích xuất qua model.
export type { ExtractionModel, TurnExtraction } from "../../../lib/api/demoDebug";

export type Phase = "idle" | "starting" | "active" | "sending" | "ended";
export type BotState = Schemas["TurnResponse"]["state"];
export type Outcome = NonNullable<Schemas["TurnResponse"]["outcome"]>;

export interface Message {
  id: string;
  role: "bot" | "caller";
  text: string;
  turn: number;
  audioUrl: string | null;
  meta: string;
}

/** Request/response gần nhất, hiện ở panel debug. */
export interface Exchange {
  method: string;
  path: string;
  request: unknown;
  status: number;
  response: unknown;
}

export interface Notice {
  tone: "info" | "success" | "error";
  text: string;
}

export interface CallSession {
  phase: Phase;
  /** Lượt người gọi kế tiếp; lời chào của bot là lượt 0. */
  nextTurn: number;
  messages: Message[];
  botState: BotState | null;
  outcome: Outcome | null;
  extraction: TurnExtraction | null;
  exchange: Exchange | null;
  notice: Notice | null;
  /** Mã lỗi backend của thao tác lỗi gần nhất (vd. BAD_KEY) để form đánh dấu ô cần sửa. */
  errorCode: string | null;
}

export interface Reply {
  utterance: string;
  audioUrl: string | null;
  state: BotState;
  debug: DemoDebug;
  elapsedMs: number;
  exchange: Exchange;
}

export type CallAction =
  | { type: "start" }
  | { type: "started"; reply: Reply }
  | { type: "turnSent" }
  | {
      type: "turnDone";
      turn: number;
      caller: { text: string; audioUrl: string | null };
      reply: Reply;
      ended: boolean;
      outcome: Outcome | null;
    }
  | { type: "failed"; message: string; code: string | null; exchange: Exchange | null }
  | { type: "notice"; notice: Notice | null }
  | { type: "clearError" }
  | { type: "reset" };

export const initialSession: CallSession = {
  phase: "idle",
  nextTurn: 1,
  messages: [],
  botState: null,
  outcome: null,
  extraction: null,
  exchange: null,
  notice: null,
  errorCode: null,
};

export function callReducer(state: CallSession, action: CallAction): CallSession {
  switch (action.type) {
    case "start":
      if (state.phase !== "idle") return state;
      return {
        ...initialSession,
        phase: "starting",
        notice: { tone: "info", text: "Đang mở cuộc gọi…" },
      };

    case "started":
      if (state.phase !== "starting") return state;
      return {
        ...state,
        phase: "active",
        messages: [botMessage(0, action.reply)],
        botState: action.reply.state,
        exchange: action.reply.exchange,
        notice: { tone: "info", text: "Cuộc gọi đã mở. Gửi lần lượt từng lượt của người gọi." },
        errorCode: null,
      };

    case "turnSent":
      if (state.phase !== "active") return state;
      return { ...state, phase: "sending", notice: null };

    case "turnDone": {
      if (state.phase !== "sending" || action.turn !== state.nextTurn) return state;
      const { turn, caller, reply, ended, outcome } = action;
      return {
        ...state,
        phase: ended ? "ended" : "active",
        nextTurn: turn + 1,
        messages: [
          ...state.messages,
          {
            id: `${turn}-caller`,
            role: "caller",
            text: caller.text,
            turn,
            audioUrl: caller.audioUrl,
            meta: `NGƯỜI GỌI · lượt ${turn}${caller.audioUrl ? " · WAV" : ""}`,
          },
          botMessage(turn, reply),
        ],
        botState: reply.state,
        outcome,
        extraction: { turn, fields: reply.debug.fields },
        exchange: reply.exchange,
        notice: ended
          ? { tone: "success", text: `Cuộc gọi đã kết thúc: ${outcome ?? "—"}.` }
          : null,
        errorCode: null,
      };
    }

    case "failed": {
      const phase =
        state.phase === "starting" ? "idle" : state.phase === "sending" ? "active" : state.phase;
      return {
        ...state,
        phase,
        exchange: action.exchange ?? state.exchange,
        notice: { tone: "error", text: action.message },
        errorCode: action.code,
      };
    }

    case "notice":
      return { ...state, notice: action.notice };

    case "clearError":
      return state.errorCode === null ? state : { ...state, errorCode: null };

    case "reset":
      return initialSession;
  }
}

function botMessage(turn: number, reply: Reply): Message {
  return {
    id: `${turn}-bot`,
    role: "bot",
    text: reply.utterance,
    turn,
    audioUrl: reply.audioUrl,
    meta: messageMeta(turn, reply.state, reply.debug, reply.elapsedMs),
  };
}

// Selector: nút nào bật được suy ra từ pha, không lưu riêng.
export const isConfigLocked = (state: CallSession) => state.phase !== "idle";
export const canStart = (state: CallSession) => state.phase === "idle";
export const canSend = (state: CallSession) => state.phase === "active";
export const isBusy = (state: CallSession) =>
  state.phase === "starting" || state.phase === "sending";
