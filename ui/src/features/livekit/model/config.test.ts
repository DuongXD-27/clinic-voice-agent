import { describe, expect, it } from "vitest";

import { DEFAULT_LIVEKIT_CONFIG, toTokenRequest, validateConfig } from "./config";

describe("LiveKit config", () => {
  it("inbound gửi số đã bỏ khoảng trắng; để trống thành null (kịch bản chuyển máy)", () => {
    const inbound = { ...DEFAULT_LIVEKIT_CONFIG, direction: "inbound" as const };
    expect(toTokenRequest({ ...inbound, callerNumber: " 0912 " })).toEqual({
      direction: "inbound",
      caller_number: "0912",
    });
    expect(toTokenRequest({ ...inbound, callerNumber: "  " })).toEqual({
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
    expect(
      validateConfig({ ...DEFAULT_LIVEKIT_CONFIG, direction: "inbound", callerNumber: "" }),
    ).toBeNull();
  });
});

describe("ASR choice", () => {
  it("omits asr_provider when following the server config", () => {
    expect(toTokenRequest(DEFAULT_LIVEKIT_CONFIG)).not.toHaveProperty("asr_provider");
  });

  it("sends the chosen ASR for this call", () => {
    expect(toTokenRequest({ ...DEFAULT_LIVEKIT_CONFIG, asrProvider: "gemini_live" })).toEqual({
      direction: "outbound",
      appointment_id: "apt_00417",
      asr_provider: "gemini_live",
    });
  });
});
