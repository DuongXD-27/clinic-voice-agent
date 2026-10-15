import type { Schemas } from "../../../lib/api/types";

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

export const DEFAULT_LIVEKIT_CONFIG: LiveKitConfig = {
  direction: "inbound",
  callerNumber: "0912345600",
  appointmentId: "apt_00417",
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
