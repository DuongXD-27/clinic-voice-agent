import type { ChatMessage } from "../../../components/chat/Conversation";
import { toExtractionFields, type TurnExtraction } from "../../../lib/api/demoDebug";

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

/** Độ trễ một lượt (call_bridge.py `_publish_timing`), ms; thiếu phần nào thì bỏ phần đó. */
export interface TurnTiming {
  turn: number;
  asrMode: string | null;
  waitSilence?: number;
  asrDecode?: number;
  turnWait?: number;
  engine?: number;
  ttsFirstAudio?: number;
  total?: number;
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
  /** Độ trễ lượt (chỉ lời bot, tới sau khi bot có tiếng). */
  timing?: TurnTiming | null;
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

/** Gói `{type: "timing", turn, ...ms}` cùng topic transcript; sai dạng thì bỏ qua. */
export function parseTiming(payload: Uint8Array): TurnTiming | null {
  const data = decode(payload);
  if (data?.type !== "timing" || typeof data.turn !== "number") return null;
  const pick = (key: string, as: keyof TurnTiming) =>
    typeof data[key] === "number" ? { [as]: data[key] } : {};
  return {
    turn: data.turn,
    asrMode: typeof data.asr_mode === "string" ? data.asr_mode : null,
    ...pick("wait_silence", "waitSilence"),
    ...pick("asr_decode", "asrDecode"),
    ...pick("turn_wait", "turnWait"),
    ...pick("engine", "engine"),
    ...pick("tts_first_audio", "ttsFirstAudio"),
    ...pick("total", "total"),
  };
}

/** "⏱ 3,50s = chờ im lặng 1,20 · ASR tên 0,20 · chốt lượt 0,70 · engine 0,90 · TTS 0,49". */
export function formatTiming(timing: TurnTiming): string {
  const s = (ms: number) => (ms / 1000).toFixed(2).replace(".", ",");
  const mode =
    timing.asrMode === "name" ? "ASR tên" : timing.asrMode === "hotword" ? "ASR hotword" : "ASR";
  const parts = [
    timing.waitSilence === undefined ? null : `chờ im lặng ${s(timing.waitSilence)}`,
    timing.asrDecode === undefined ? null : `${mode} ${s(timing.asrDecode)}`,
    timing.turnWait === undefined ? null : `chốt lượt ${s(timing.turnWait)}`,
    timing.engine === undefined ? null : `engine ${s(timing.engine)}`,
    timing.ttsFirstAudio === undefined ? null : `TTS ${s(timing.ttsFirstAudio)}`,
  ].filter(Boolean);
  const total = timing.total === undefined ? "⏱" : `⏱ ${s(timing.total)}s =`;
  return `${total} ${parts.join(" · ")}`;
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
      : [
          `BOT · lượt ${line.turn}`,
          line.state,
          line.outcome,
          line.timing ? formatTiming(line.timing) : null,
        ];
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
