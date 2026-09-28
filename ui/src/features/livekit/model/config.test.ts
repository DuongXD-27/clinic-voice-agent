import { describe, expect, it } from "vitest";

import { DEFAULT_LIVEKIT_CONFIG, toTokenRequest, validateConfig } from "./config";

describe("LiveKit config", () => {
  it("inbound gửi số đã bỏ khoảng trắng; để trống thành null (kịch bản chuyển máy)", () => {
    expect(toTokenRequest({ ...DEFAULT_LIVEKIT_CONFIG, callerNumber: " 0912 " })).toEqual({
      direction: "inbound",
      caller_number: "0912",
    });
    expect(toTokenRequest({ ...DEFAULT_LIVEKIT_CONFIG, callerNumber: "  " })).toEqual({
      direction: "inbound",
      caller_number: null,
    });
  });

  it("outbound chỉ gửi appointment_id", () => {
    expect(
      toTokenRequest({
        ...DEFAULT_LIVEKIT_CONFIG,
        direction: "outbound",
        appointmentId: " apt_1 ",
      }),
    ).toEqual({ direction: "outbound", appointment_id: "apt_1" });
  });

  it("outbound thiếu lịch hẹn thì chặn; inbound trống số vẫn cho qua", () => {
    expect(
      validateConfig({ ...DEFAULT_LIVEKIT_CONFIG, direction: "outbound", appointmentId: "" }),
    ).toContain("Appointment ID");
    expect(validateConfig({ ...DEFAULT_LIVEKIT_CONFIG, callerNumber: "" })).toBeNull();
  });
});
