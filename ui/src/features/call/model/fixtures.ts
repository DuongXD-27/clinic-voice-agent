import type { Schemas } from "../../../lib/api/types";
import { DEFAULT_APPOINTMENT } from "./config";

/** Dữ liệu clinic cho dropdown (GET /demo-api/clinic-fixtures). */
export type FixturesState =
  | { status: "loading" }
  | { status: "ready"; data: Schemas["ClinicFixtures"] }
  | { status: "error"; message: string };

export interface Option {
  value: string;
  label: string;
}

/** Lịch hẹn kèm trạng thái; luôn có lựa chọn đang chọn dù fixtures lỗi hay chưa tải. */
export function appointmentOptions(state: FixturesState, current: string): Option[] {
  const options =
    state.status === "ready"
      ? state.data.appointments.map((item) => ({
          value: item.appointment_id,
          label: [item.appointment_id, item.status, item.display_name].filter(Boolean).join(" · "),
        }))
      : [];
  for (const value of [current, DEFAULT_APPOINTMENT]) {
    if (value && !options.some((option) => option.value === value)) {
      options.push({ value, label: value });
    }
  }
  return options;
}

export function phoneOptions(state: FixturesState): Option[] {
  if (state.status !== "ready") return [];
  return state.data.phones.map((item) => ({
    value: item.phone,
    label: [item.phone, item.display_name].filter(Boolean).join(" · "),
  }));
}

export function fixturesHint(state: FixturesState): string {
  switch (state.status) {
    case "loading":
      return "Đang tải dữ liệu clinic…";
    case "error":
      return `Không tải được dữ liệu clinic (${state.message}). Vẫn nhập tay được.`;
    case "ready": {
      const source = state.data.source === "sim" ? "clinic giả (local)" : "clinic mock";
      return `Nguồn: ${source} · ${state.data.appointments.length} lịch hẹn · ${state.data.phones.length} số điện thoại`;
    }
  }
}
