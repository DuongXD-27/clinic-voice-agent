import type { Schemas } from "../../../lib/api/types";

type TokenRequest = Schemas["LiveKitTokenRequest"];
export type Direction = NonNullable<TokenRequest["direction"]>;

export interface LiveKitConfig {
  direction: Direction;
  /** inbound: để trống là kịch bản hợp lệ — bot không định danh được, chuyển máy ngay lượt đầu. */
  callerNumber: string;
  /** outbound: bắt buộc. */
  appointmentId: string;
}

export const DEFAULT_LIVEKIT_CONFIG: LiveKitConfig = {
  direction: "inbound",
  callerNumber: "0912345600",
  appointmentId: "apt_00417",
};

/** Cùng luật với LiveKitTokenRequest; định dạng số điện thoại để backend kiểm. */
export function validateConfig(config: LiveKitConfig): string | null {
  if (config.direction === "outbound" && !config.appointmentId.trim()) {
    return "Cuộc gọi outbound cần Appointment ID.";
  }
  return null;
}

export function toTokenRequest(config: LiveKitConfig): TokenRequest {
  return config.direction === "outbound"
    ? { direction: "outbound", appointment_id: config.appointmentId.trim() }
    : { direction: "inbound", caller_number: config.callerNumber.trim() || null };
}
