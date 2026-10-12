/**
 * Trạng thái trang thử STT, dạng reducer thuần (không biết gì về livekit-client).
 *
 *   idle ─connecting─▶ connecting ─connected─▶ listening
 *     ▲                    │ failed                 │ disconnected / failed
 *     └────────────────────┴────────────────────────┘
 *
 * Worker (chế độ `mode=stt`, callbot.transports.livekit.stt_session) gửi từng lượt qua data
 * channel: `partial` thay chữ của lượt đang nói, `final` chốt lượt (đúng chữ engine nhận trong
 * cuộc gọi thật), `dropped` = ASR nghe ra chữ nhưng pipeline bỏ (chỉ có từ đệm, Validator).
 * Các lượt giữ lại sau khi kết thúc để xem lại; chỉ xoá khi bắt đầu phiên mới.
 */

/** Topic data channel của worker (STT_TOPIC trong stt_session.py). */
export const STT_TOPIC = "callbot.stt";

export type SttAsr = "zipformer" | "gemini_live" | "elevenlabs_realtime";

export const STT_ASR_CHOICES = [
  { value: "zipformer", label: "ZipFormer" },
  { value: "gemini_live", label: "Gemini Live" },
  { value: "elevenlabs_realtime", label: "ElevenLabs Realtime" },
] as const satisfies readonly { value: SttAsr; label: string }[];

export interface SttMessage {
  kind: "partial" | "final" | "dropped";
  turn: number;
  text: string;
  confidence: number | null;
  /** Từ lúc bắt đầu nói tới final (ms), chỉ có ở `final`. */
  finalMs: number | null;
}

export interface SttTurn {
  /** Khoá hiển thị: lượt bị bỏ không tăng số lượt nên `turn` có thể lặp lại. */
  id: number;
  turn: number;
  text: string;
  status: "live" | "final" | "dropped";
  confidence: number | null;
  finalMs: number | null;
}

export type SttPhase = "idle" | "connecting" | "listening";

export interface SttSession {
  phase: SttPhase;
  /** Bước đang làm khi connecting (lấy token, vào room, bật mic). */
  step: string | null;
  /** Worker đã vào room (chưa vào thì chưa có ai nghe). */
  workerPresent: boolean;
  /** ASR worker báo đang dùng. */
  workerAsr: string | null;
  turns: SttTurn[];
  error: string | null;
}

export type SttAction =
  | { type: "connecting"; step: string }
  | { type: "connected"; workerPresent: boolean }
  | { type: "workerPresence"; present: boolean }
  | { type: "workerAsr"; provider: string }
  | { type: "message"; message: SttMessage }
  | { type: "disconnected" }
  | { type: "failed"; message: string };

export const initialStt: SttSession = {
  phase: "idle",
  step: null,
  workerPresent: false,
  workerAsr: null,
  turns: [],
  error: null,
};

export function sttReducer(state: SttSession, action: SttAction): SttSession {
  switch (action.type) {
    case "connecting":
      if (state.phase === "listening") return state;
      return state.phase === "idle"
        ? { ...initialStt, phase: "connecting", step: action.step }
        : { ...state, step: action.step };
    case "connected":
      if (state.phase !== "connecting") return state;
      return {
        ...state,
        phase: "listening",
        step: null,
        workerPresent: state.workerPresent || action.workerPresent,
      };
    case "workerPresence":
      if (state.phase === "idle") return state;
      return { ...state, workerPresent: action.present };
    case "workerAsr":
      if (state.phase === "idle") return state;
      return { ...state, workerAsr: action.provider };
    case "message":
      if (state.phase === "idle") return state;
      return { ...state, turns: applyMessage(state.turns, action.message) };
    case "disconnected":
      if (state.phase === "idle") return state;
      // ASR worker báo chỉ đúng cho phiên vừa xong: giữ lại thì đổi model sau đó bị cảnh báo
      // "khác lựa chọn" sai.
      return {
        ...state,
        phase: "idle",
        step: null,
        workerPresent: false,
        workerAsr: null,
        turns: closeLive(state.turns),
      };
    case "failed":
      return {
        ...state,
        phase: "idle",
        step: null,
        workerPresent: false,
        workerAsr: null,
        turns: closeLive(state.turns),
        error: action.message,
      };
  }
}

function applyMessage(turns: SttTurn[], message: SttMessage): SttTurn[] {
  // Dòng đang nghe của lượt này — không nhất thiết là dòng cuối: cổng giọng còn chấm lượt k thì
  // lượt k+1 đã có chữ tạm thời, kết cục của lượt k tới sau.
  let open = -1;
  turns.forEach((turn, index) => {
    if (turn.status === "live" && turn.turn === message.turn) open = index;
  });
  const replaceOpen = (update: (turn: SttTurn) => SttTurn) =>
    turns.map((turn, index) => (index === open ? update(turn) : turn));
  if (message.kind === "partial") {
    // Partial tới muộn của lượt đã chốt: bỏ (worker đã lọc, đây là lưới an toàn).
    if (turns.some((turn) => turn.status === "final" && turn.turn === message.turn)) return turns;
    if (open >= 0) return replaceOpen((turn) => ({ ...turn, text: message.text }));
    return [...turns, newTurn(turns, message, "live")];
  }
  const closed = newTurn(turns, message, message.kind === "final" ? "final" : "dropped");
  return open >= 0 ? replaceOpen((turn) => ({ ...closed, id: turn.id })) : [...turns, closed];
}

function newTurn(turns: SttTurn[], message: SttMessage, status: SttTurn["status"]): SttTurn {
  return {
    id: nextId(turns),
    turn: message.turn,
    text: message.text,
    status,
    confidence: message.confidence,
    finalMs: message.finalMs,
  };
}

const nextId = (turns: SttTurn[]) => (turns.at(-1)?.id ?? 0) + 1;

/** Phiên kết thúc giữa lúc đang nói: dòng tạm thời không còn được chốt nữa. */
function closeLive(turns: SttTurn[]): SttTurn[] {
  const last = turns.at(-1);
  return last?.status === "live" ? [...turns.slice(0, -1), { ...last, status: "dropped" }] : turns;
}

const decoder = new TextDecoder();

/** JSON UTF-8 từ `publish_data`; sai dạng thì bỏ qua (không làm hỏng trang). */
export function parseSttMessage(payload: Uint8Array): SttMessage | null {
  let data: unknown;
  try {
    data = JSON.parse(decoder.decode(payload));
  } catch {
    return null;
  }
  if (typeof data !== "object" || data === null || Array.isArray(data)) return null;
  const record = data as Record<string, unknown>;
  const { kind, turn, text } = record;
  if (
    record.type !== "stt" ||
    (kind !== "partial" && kind !== "final" && kind !== "dropped") ||
    typeof turn !== "number" ||
    typeof text !== "string"
  ) {
    return null;
  }
  return {
    kind,
    turn,
    text,
    confidence: typeof record.confidence === "number" ? record.confidence : null,
    finalMs: typeof record.final_ms === "number" ? record.final_ms : null,
  };
}

/** Dòng phụ dưới mỗi lượt: số lượt, độ tin cậy, thời gian tới khi chốt. */
export function describeTurn(turn: SttTurn): string {
  if (turn.status === "live") return `Lượt ${String(turn.turn)} · đang nghe`;
  if (turn.status === "dropped") return `Lượt ${String(turn.turn)} · không thành lượt`;
  const parts = [`Lượt ${String(turn.turn)}`];
  if (turn.confidence !== null) parts.push(`${String(Math.round(turn.confidence * 100))}%`);
  if (turn.finalMs !== null) {
    parts.push(`chốt sau ${(turn.finalMs / 1000).toFixed(1).replace(".", ",")} s`);
  }
  return parts.join(" · ");
}

/** Dòng trạng thái góc dưới bên trái. */
export function describeStatus(state: SttSession): {
  tone: "success" | "warning" | "neutral";
  label: string;
  pulse: boolean;
} {
  if (state.phase === "connecting") {
    return { tone: "neutral", label: state.step ?? "Đang kết nối…", pulse: true };
  }
  if (state.phase === "listening") {
    return state.workerPresent
      ? { tone: "success", label: "Đang nghe", pulse: true }
      : { tone: "warning", label: "Đang chờ worker vào phòng…", pulse: true };
  }
  return { tone: "neutral", label: "Chưa kết nối", pulse: false };
}
