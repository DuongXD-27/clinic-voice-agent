import type { ChatMessage } from "../../../components/chat/Conversation";
import { toExtractionFields, type TurnExtraction } from "../../../lib/api/demoDebug";

/** Topic data channel worker gửi lời thoại (TRANSCRIPT_TOPIC trong call_bridge.py). */
export const TRANSCRIPT_TOPIC = "callbot.transcript";
/** Topic worker báo lỗi không mở được cuộc gọi (vd. lịch outbound không dùng được). */
export const STATUS_TOPIC = "callbot.status";

export interface TranscriptLine {
  role: "bot" | "caller";
  /** Lượt hội thoại; câu chào của bot là lượt 0. */
  turn: number;
  text: string;
  /** Độ tin cậy ASR, chỉ có ở lời người gọi. */
  confidence: number | null;
  /** State / kết thúc / outcome sau câu bot, chỉ có ở lời bot. */
  state: string | null;
  ended: boolean;
  outcome: string | null;
  /**
   * Chỉ ở câu bot của lượt ≥ 1, khi worker bật `demo_debug` (config/livekit.yaml): trích xuất của
   * lượt, gửi cùng gói với câu bot. Không có = worker không gửi; "invalid" = gửi sai dạng.
   */
  extraction?: TurnExtraction | "invalid";
}

const decoder = new TextDecoder();

/** JSON UTF-8 từ `publish_data`; sai dạng thì bỏ qua (không làm hỏng trang). */
export function parseTranscript(payload: Uint8Array): TranscriptLine | null {
  const data = decode(payload);
  if (data?.type !== "transcript") return null;
  const { role, turn, text } = data;
  if (
    (role !== "bot" && role !== "caller") ||
    typeof turn !== "number" ||
    typeof text !== "string"
  ) {
    return null;
  }
  const line: TranscriptLine = {
    role,
    turn,
    text,
    confidence: typeof data.confidence === "number" ? data.confidence : null,
    state: typeof data.state === "string" ? data.state : null,
    ended: data.ended === true,
    outcome: typeof data.outcome === "string" ? data.outcome : null,
  };
  if (role === "bot" && "extraction" in data)
    line.extraction = readExtraction(turn, data.extraction);
  return line;
}

/** `extraction_view` (extraction_view.py); null = lượt không qua bước trích xuất (vd. lượt replay). */
function readExtraction(turn: number, raw: unknown): TurnExtraction | "invalid" {
  if (raw === null) return { turn, fields: null };
  const fields = toExtractionFields(raw);
  return fields ? { turn, fields } : "invalid";
}

/** Thông báo lỗi trên STATUS_TOPIC (`{code, message}`); sai dạng thì bỏ qua. */
export function parseStatus(payload: Uint8Array): string | null {
  const data = decode(payload);
  if (!data || typeof data.message !== "string") return null;
  return data.message;
}

export function toChatMessage(line: TranscriptLine, index: number): ChatMessage {
  const meta =
    line.role === "caller"
      ? [
          `NGƯỜI GỌI · lượt ${line.turn}`,
          line.confidence === null ? null : `ASR ${Math.round(line.confidence * 100)}%`,
        ]
      : [`BOT · lượt ${line.turn}`, line.state, line.outcome];
  return {
    id: `${index}-${line.role}-${line.turn}`,
    role: line.role,
    text: line.text || "(không nghe rõ)",
    meta: meta.filter(Boolean).join(" · "),
  };
}

function decode(payload: Uint8Array): Record<string, unknown> | null {
  try {
    const data: unknown = JSON.parse(decoder.decode(payload));
    return isRecord(data) ? data : null;
  } catch {
    return null;
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
