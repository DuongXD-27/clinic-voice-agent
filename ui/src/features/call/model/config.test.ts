import { describe, expect, it } from "vitest";

import {
  defaultConfig,
  newCallId,
  toStartRequest,
  validateConfig,
  type CallConfig,
} from "./config";

const base: CallConfig = defaultConfig(0);

describe("newCallId", () => {
  it("sinh Call ID hợp lệ theo thời gian", () => {
    expect(newCallId(1_000_000)).toBe("c_demo_lfls");
    expect(validateConfig({ ...base, callId: newCallId() })).toBeNull();
  });
});

describe("validateConfig", () => {
  it.each([
    ["Call ID có ký tự lạ", { callId: "c/../x" }, "Call ID"],
    ["Call ID rỗng", { callId: "  " }, "Call ID"],
    ["outbound thiếu lịch hẹn", { direction: "outbound", appointmentId: "" }, "Appointment ID"],
    ["inbound thiếu số gọi", { direction: "inbound", callerNumber: " " }, "số điện thoại"],
    ["max turns rỗng", { maxTurns: Number.NaN }, "Max turns"],
    ["max turns bằng 0", { maxTurns: 0 }, "Max turns"],
    ["max turns lẻ", { maxTurns: 1.5 }, "Max turns"],
  ] as const)("chặn %s", (_name, patch, fragment) => {
    expect(validateConfig({ ...base, ...patch })).toContain(fragment);
  });

  it("cho qua cấu hình mặc định", () => {
    expect(validateConfig(base)).toBeNull();
  });
});

describe("toStartRequest", () => {
  it("outbound chỉ gửi appointment_id", () => {
    expect(toStartRequest({ ...base, callId: " c1 ", appointmentId: " apt_1 " })).toEqual({
      call_id: "c1",
      direction: "outbound",
      appointment_id: "apt_1",
      caller_number: null,
      locale: "vi-VN",
      mode: "text",
      max_turns: 20,
    });
  });

  it("inbound chỉ gửi caller_number; locale rỗng về vi-VN", () => {
    const body = toStartRequest({
      ...base,
      direction: "inbound",
      callerNumber: " 0912 ",
      locale: " ",
      mode: "audio",
    });

    expect(body).toMatchObject({
      direction: "inbound",
      appointment_id: null,
      caller_number: "0912",
      locale: "vi-VN",
      mode: "audio",
    });
  });
});
