import type { ChatMessage } from "../../../components/chat/Conversation";

/** Topic data channel worker gửi lời thoại (TRANSCRIPT_TOPIC trong call_bridge.py). */
export const TRANSCRIPT_TOPIC = "callbot.transcript";

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
}

const decoder = new TextDecoder();

/** JSON UTF-8 từ `publish_data`; sai dạng thì bỏ qua (không làm hỏng trang). */
export function parseTranscript(payload: Uint8Array): TranscriptLine | null {
  let data: unknown;
  try {
    data = JSON.parse(decoder.decode(payload));
  } catch {
    return null;
  }
  if (!isRecord(data) || data.type !== "transcript") return null;
  const { role, turn, text } = data;
  if (
    (role !== "bot" && role !== "caller") ||
    typeof turn !== "number" ||
    typeof text !== "string"
  ) {
    return null;
  }
  return {
    role,
    turn,
    text,
    confidence: typeof data.confidence === "number" ? data.confidence : null,
    state: typeof data.state === "string" ? data.state : null,
    ended: data.ended === true,
    outcome: typeof data.outcome === "string" ? data.outcome : null,
  };
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

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
