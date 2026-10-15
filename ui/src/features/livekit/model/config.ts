import type { Schemas } from "../../../lib/api/types";
import { DEFAULT_APPOINTMENT, DEFAULT_CALLER } from "../../call/model/config";

type TokenRequest = Schemas["LiveKitTokenRequest"];
export type Direction = NonNullable<TokenRequest["direction"]>;
/** "server": không gửi lựa chọn, worker dùng ASR cấu hình sẵn (LIVEKIT_ASR_PROVIDER / ASR_PROVIDER). */
export type AsrChoice = NonNullable<TokenRequest["asr_provider"]> | "server";

export interface LiveKitConfig {
  direction: Direction;
  /** inbound: để trống là kịch bản hợp lệ — bot không định danh được, chuyển máy ngay lượt đầu. */
  callerNumber: string;
  /** outbound: bắt buộc. */
  appointmentId: string;
  /** ASR cho cuộc gọi này; đổi được giữa các cuộc gọi, không cần khởi động lại worker. */
  asrProvider: AsrChoice;
}

/** Cùng mặc định với trang gọi HTTP (call/model/config.ts): outbound, lịch mẫu của clinic mock. */
export const DEFAULT_LIVEKIT_CONFIG: LiveKitConfig = {
  direction: "outbound",
  callerNumber: DEFAULT_CALLER,
  appointmentId: DEFAULT_APPOINTMENT,
  asrProvider: "server",
};

/** Cùng luật với LiveKitTokenRequest; định dạng số điện thoại để backend kiểm. */
export function validateConfig(config: LiveKitConfig): string | null {
  if (config.direction === "outbound" && !config.appointmentId.trim()) {
    return "Cuộc gọi outbound cần Appointment ID.";
  }
  return null;
}

export function toTokenRequest(config: LiveKitConfig): TokenRequest {
  const request: TokenRequest =
    config.direction === "outbound"
      ? { direction: "outbound", appointment_id: config.appointmentId.trim() }
      : { direction: "inbound", caller_number: config.callerNumber.trim() || null };
  return config.asrProvider === "server"
    ? request
    : { ...request, asr_provider: config.asrProvider };
}

export const ASR_LABELS: Record<string, string> = {
  zipformer: "GipFormer",
  gemini_live: "Gemini Live",
  elevenlabs_realtime: "ElevenLabs Realtime",
};
