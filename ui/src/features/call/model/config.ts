import type { Schemas } from "../../../lib/api/types";

export type Direction = Schemas["StartCallRequest"]["direction"];
export type Mode = Schemas["StartCallRequest"]["mode"];

export interface CallConfig {
  callId: string;
  direction: Direction;
  mode: Mode;
  /** Chỉ dùng khi outbound. */
  appointmentId: string;
  /** Chỉ dùng khi inbound. */
  callerNumber: string;
  locale: string;
  maxTurns: number;
}

/** Lịch outbound và số inbound mẫu của clinic mock (docs/reference/clinic-mock.md). */
export const DEFAULT_APPOINTMENT = "apt_00417";
export const DEFAULT_CALLER = "0912345600";

const CALL_ID_PATTERN = /^[A-Za-z0-9_-]{1,128}$/;

export function newCallId(now: number = Date.now()): string {
  return `c_demo_${now.toString(36)}`;
}

export function defaultConfig(now?: number): CallConfig {
  return {
    callId: newCallId(now),
    direction: "outbound",
    mode: "text",
    appointmentId: DEFAULT_APPOINTMENT,
    callerNumber: DEFAULT_CALLER,
    locale: "vi-VN",
    maxTurns: 20,
  };
}

/** Lỗi đầu tiên người dùng cần sửa, hoặc null nếu gửi được. Cùng luật với StartCallRequest. */
export function validateConfig(config: CallConfig): string | null {
  if (!CALL_ID_PATTERN.test(config.callId.trim())) {
    return "Call ID chỉ được chứa chữ, số, dấu gạch dưới hoặc gạch ngang (tối đa 128 ký tự).";
  }
  if (config.direction === "outbound" && !config.appointmentId.trim()) {
    return "Cuộc gọi outbound cần Appointment ID.";
  }
  if (config.direction === "inbound" && !config.callerNumber.trim()) {
    return "Cuộc gọi inbound cần số điện thoại người gọi.";
  }
  if (!Number.isInteger(config.maxTurns) || config.maxTurns < 1) {
    return "Max turns phải là số nguyên lớn hơn 0.";
  }
  return null;
}

export function toStartRequest(config: CallConfig): Schemas["StartCallRequest"] {
  const inbound = config.direction === "inbound";
  return {
    call_id: config.callId.trim(),
    direction: config.direction,
    appointment_id: inbound ? null : config.appointmentId.trim(),
    caller_number: inbound ? config.callerNumber.trim() : null,
    locale: config.locale.trim() || "vi-VN",
    mode: config.mode,
    max_turns: config.maxTurns,
  };
}
