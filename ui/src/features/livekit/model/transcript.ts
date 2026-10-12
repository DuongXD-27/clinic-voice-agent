import type { ChatMessage } from "../../../components/chat/Conversation";

/** Topic data channel worker gửi lời thoại (TRANSCRIPT_TOPIC trong call_bridge.py). */
export const TRANSCRIPT_TOPIC = "callbot.transcript";
/** Topic worker báo lỗi không mở được cuộc gọi (vd. lịch outbound không dùng được). */
export const STATUS_TOPIC = "callbot.status";

/** Một phương án ASR trong top N (call_bridge.py `_publish_nbest`): log-xác suất và tỉ lệ. */
export interface NBestHyp {
  text: string;
  logProb: number;
  share: number;
  /** Phần điểm hotword trong `logProb` (điểm cuối); 0/thiếu = không khớp cụm nào. */
  bonus?: number;
  /** Dòng giả cuối nhóm: `text` là các cụm hotword của lượt, không phải phương án. */
  hotwords?: boolean;
}

/** Top N phương án của từng final trong một lượt người gọi (tới sau lời người gọi). */
export interface NBestUpdate {
  turn: number;
  segments: NBestHyp[][];
}

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
  /** Top N phương án ASR (chỉ lời người gọi, tới sau); null = chưa có / không bật. */
  nbest?: NBestHyp[][] | null;
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

/** Gói `{type: "nbest", turn, segments}` cùng topic transcript; sai dạng thì bỏ qua. */
export function parseNBest(payload: Uint8Array): NBestUpdate | null {
  const data = decode(payload);
  if (data?.type !== "nbest" || typeof data.turn !== "number" || !Array.isArray(data.segments)) {
    return null;
  }
  const hotwords: unknown[] = Array.isArray(data.hotwords) ? data.hotwords : [];
  const segments = data.segments.flatMap((segment: unknown, index: number) => {
    if (!Array.isArray(segment)) return [];
    const hyps: NBestHyp[] = segment.filter(isRecord).flatMap((hyp) =>
      typeof hyp.text === "string" &&
      typeof hyp.log_prob === "number" &&
      typeof hyp.share === "number"
        ? [
            {
              text: hyp.text,
              logProb: hyp.log_prob,
              share: hyp.share,
              ...(typeof hyp.bonus === "number" && hyp.bonus !== 0 ? { bonus: hyp.bonus } : {}),
            },
          ]
        : [],
    );
    if (hyps.length === 0) return [];
    const listed = hotwords[index];
    const phrases = Array.isArray(listed)
      ? listed.filter((p): p is string => typeof p === "string")
      : [];
    return [
      phrases.length
        ? [...hyps, { text: phrases.join(", "), logProb: 0, share: 0, hotwords: true }]
        : hyps,
    ];
  });
  return segments.length ? { turn: data.turn, segments } : null;
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
    ...(line.nbest?.length
      ? {
          candidates: line.nbest.map((segment) =>
            segment.map((hyp) => ({
              text: hyp.hotwords ? `(hotword): ${hyp.text}` : hyp.text,
              score: hyp.hotwords ? "" : candidateScore(hyp),
            })),
          ),
        }
      : {}),
  };
}

/** Điểm cuối · tỉ lệ, kèm phần hotword đã cộng nếu có: "+5.06 · 98% (hotword +9.0)". */
function candidateScore(hyp: NBestHyp): string {
  const score = `${hyp.logProb > 0 ? "+" : ""}${hyp.logProb.toFixed(2)}`;
  const base = `${score} · ${Math.round(hyp.share * 100)}%`;
  return hyp.bonus ? `${base} (hotword +${hyp.bonus.toFixed(1)})` : base;
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
