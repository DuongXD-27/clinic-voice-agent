/**
 * Trạng thái một cuộc gọi LiveKit, dạng reducer thuần. Sự kiện của Room (livekit-client) được
 * dịch thành action ở useLiveKitCall; reducer không biết gì về SDK nên test được không cần WebRTC.
 *
 *   idle ─connecting─▶ connecting ─connected─▶ connected ⇄ reconnecting
 *     ▲                    │ failed                 │ disconnected
 *     └────────────────────┴────────────────────────┘
 *
 * Transcript và trích xuất (worker gửi qua data channel) giữ lại sau khi ngắt để xem lại; chỉ
 * xoá khi bắt đầu cuộc gọi mới.
 */

import type { TurnExtraction } from "../../../lib/api/demoDebug";
import { ASR_LABELS } from "./config";
import type { TranscriptLine } from "./transcript";

export type Phase = "idle" | "connecting" | "connected" | "reconnecting";
export type Tone = "info" | "success" | "warning" | "error";

export interface LogEntry {
  id: number;
  at: number;
  text: string;
  tone: Tone;
}

export interface LiveKitSession {
  phase: Phase;
  /** Bước đang làm khi connecting (lấy token, vào room, bật mic). */
  step: string | null;
  roomName: string | null;
  micEnabled: boolean;
  botPresent: boolean;
  speaking: { bot: boolean; caller: boolean };
  /** Trình duyệt chặn phát audio cho tới khi người dùng bấm vào trang. */
  audioBlocked: boolean;
  log: LogEntry[];
  transcript: TranscriptLine[];
  /** Trích xuất của lượt người gọi gần nhất; null = chưa có (hoặc worker cũ không gửi). */
  extraction: TurnExtraction | null;
  /** State / outcome theo câu bot gần nhất trong transcript. */
  botState: string | null;
  outcome: string | null;
  notice: { tone: Tone; text: string } | null;
  /** ASR chọn trên trang cho cuộc gọi này; null = theo cấu hình worker. */
  requestedAsr: string | null;
  /** ASR worker báo đang dùng; null = chưa báo (worker cũ không báo). */
  botAsr: string | null;
}

export type LiveKitAction =
  | { type: "connecting"; step: string }
  | { type: "connected"; roomName: string; botPresent: boolean; at: number; asr?: string | null }
  | { type: "reconnecting"; at: number }
  | { type: "reconnected"; at: number }
  | { type: "disconnected"; at: number }
  | { type: "failed"; message: string; at: number }
  | { type: "micChanged"; enabled: boolean; at: number }
  | { type: "botPresence"; present: boolean; at: number }
  | { type: "botAsr"; provider: string; at: number }
  | { type: "speakers"; bot: boolean; caller: boolean }
  | { type: "audioBlocked"; blocked: boolean }
  | { type: "transcript"; line: TranscriptLine; at: number }
  | { type: "extraction"; extraction: TurnExtraction }
  | { type: "notice"; notice: LiveKitSession["notice"] };

export const initialSession: LiveKitSession = {
  phase: "idle",
  step: null,
  roomName: null,
  micEnabled: false,
  botPresent: false,
  speaking: { bot: false, caller: false },
  audioBlocked: false,
  log: [],
  transcript: [],
  extraction: null,
  botState: null,
  outcome: null,
  notice: null,
  requestedAsr: null,
  botAsr: null,
};

const SILENT = { bot: false, caller: false };
const asrLabel = (provider: string) => ASR_LABELS[provider] ?? provider;

export function liveKitReducer(state: LiveKitSession, action: LiveKitAction): LiveKitSession {
  switch (action.type) {
    case "connecting":
      if (state.phase !== "idle" && state.phase !== "connecting") return state;
      return state.phase === "idle"
        ? { ...initialSession, phase: "connecting", step: action.step }
        : { ...state, step: action.step };

    case "connected": {
      if (state.phase !== "connecting") return state;
      const joined = log(
        {
          ...state,
          phase: "connected",
          step: null,
          roomName: action.roomName,
          micEnabled: true,
          botPresent: action.botPresent,
          notice: { tone: "info", text: "Đang gọi — nói vào microphone, bot trả lời qua loa." },
          requestedAsr: action.asr ?? null,
        },
        action.at,
        `Đã vào room ${action.roomName}, microphone đang bật.`,
        "success",
      );
      return action.asr
        ? log(joined, action.at, `ASR đã chọn: ${asrLabel(action.asr)}.`, "info")
        : joined;
    }

    case "reconnecting":
      if (state.phase !== "connected") return state;
      return log(
        { ...state, phase: "reconnecting", speaking: SILENT },
        action.at,
        "Mạng gián đoạn, đang kết nối lại…",
        "warning",
      );

    case "reconnected":
      if (state.phase !== "reconnecting") return state;
      return log({ ...state, phase: "connected" }, action.at, "Đã kết nối lại.", "success");

    case "disconnected":
      if (state.phase === "idle") return state;
      return log(
        {
          ...state,
          phase: "idle",
          step: null,
          micEnabled: false,
          botPresent: false,
          speaking: SILENT,
          audioBlocked: false,
          notice: { tone: "info", text: "Cuộc gọi đã kết thúc." },
        },
        action.at,
        "Đã ngắt kết nối.",
        "info",
      );

    case "failed":
      return log(
        {
          ...state,
          phase: "idle",
          step: null,
          micEnabled: false,
          botPresent: false,
          speaking: SILENT,
          notice: { tone: "error", text: action.message },
        },
        action.at,
        `Lỗi: ${action.message}`,
        "error",
      );

    case "micChanged":
      if (state.phase === "idle" || state.micEnabled === action.enabled) return state;
      return log(
        {
          ...state,
          micEnabled: action.enabled,
          speaking: action.enabled ? state.speaking : { ...state.speaking, caller: false },
        },
        action.at,
        action.enabled ? "Đã bật microphone." : "Đã tắt microphone.",
        "info",
      );

    case "botPresence":
      if (state.phase === "idle" || state.botPresent === action.present) return state;
      return log(
        {
          ...state,
          botPresent: action.present,
          speaking: action.present ? state.speaking : { ...state.speaking, bot: false },
        },
        action.at,
        action.present ? "Bot đã vào phòng." : "Bot đã rời phòng.",
        action.present ? "success" : "warning",
      );

    case "botAsr": {
      if (state.phase === "idle") return state;
      const reported = { ...state, botAsr: action.provider };
      const used = asrLabel(action.provider);
      return state.requestedAsr && state.requestedAsr !== action.provider
        ? log(
            reported,
            action.at,
            `Bot dùng ASR: ${used} — KHÁC lựa chọn ${asrLabel(state.requestedAsr)}.`,
            "error",
          )
        : log(reported, action.at, `Bot dùng ASR: ${used}.`, "info");
    }

    case "speakers":
      if (state.phase === "idle") return state;
      if (state.speaking.bot === action.bot && state.speaking.caller === action.caller) {
        return state;
      }
      return { ...state, speaking: { bot: action.bot, caller: action.caller } };

    case "audioBlocked":
      if (state.audioBlocked === action.blocked) return state;
      return { ...state, audioBlocked: action.blocked };

    case "transcript": {
      // Nhận cả khi connecting: bot chào ngay khi mình vào room, lúc trình duyệt còn đang xin
      // quyền mic (chưa "connected"). connecting luôn bắt đầu với transcript rỗng nên không lẫn
      // cuộc gọi cũ.
      if (state.phase === "idle") return state;
      const { line } = action;
      const next = { ...state, transcript: [...state.transcript, line] };
      if (line.role !== "bot") {
        // Tới lượt người gọi đầu tiên mà bot vẫn chưa báo ASR: worker cũ, không theo lựa chọn.
        const firstCaller = !state.transcript.some((earlier) => earlier.role === "caller");
        return firstCaller && state.botAsr === null
          ? log(
              next,
              action.at,
              "Bot không báo ASR đang dùng: cuộc gọi có thể vào worker cũ, không theo lựa chọn ASR.",
              "warning",
            )
          : next;
      }
      const withState = { ...next, botState: line.state, outcome: line.outcome };
      return line.ended
        ? log(withState, action.at, `Bot kết thúc cuộc gọi: ${line.outcome ?? "—"}.`, "success")
        : withState;
    }

    case "extraction":
      // Cùng điều kiện với transcript: connecting luôn bắt đầu từ initialSession.
      if (state.phase === "idle") return state;
      return { ...state, extraction: action.extraction };

    case "notice":
      return { ...state, notice: action.notice };
  }
}

function log(state: LiveKitSession, at: number, text: string, tone: Tone): LiveKitSession {
  const id = (state.log.at(-1)?.id ?? 0) + 1;
  return { ...state, log: [...state.log, { id, at, text, tone }] };
}

export const isActive = (state: LiveKitSession) =>
  state.phase === "connected" || state.phase === "reconnecting";

/** Dòng trạng thái kết nối cho StatusIndicator. */
export function describeConnection(state: LiveKitSession): {
  tone: "success" | "warning" | "neutral";
  label: string;
  pulse: boolean;
} {
  switch (state.phase) {
    case "idle":
      return { tone: "neutral", label: "Chưa kết nối", pulse: false };
    case "connecting":
      return { tone: "neutral", label: state.step ?? "Đang kết nối…", pulse: true };
    case "connected":
      return { tone: "success", label: `Đã kết nối · ${state.roomName ?? ""}`, pulse: false };
    case "reconnecting":
      return { tone: "warning", label: "Đang kết nối lại…", pulse: true };
  }
}
