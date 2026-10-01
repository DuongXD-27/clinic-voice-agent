import { describe, expect, it } from "vitest";

import { audioSettingsAttribute } from "./audioSettings";

describe("audioSettingsAttribute", () => {
  it("keeps only processing flags and numeric format, never device identifiers", () => {
    const value = audioSettingsAttribute({
      deviceId: "abc",
      groupId: "def",
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: false,
      voiceIsolation: true,
      sampleRate: 48000,
      channelCount: 1,
    } as MediaTrackSettings);

    expect(JSON.parse(value)).toEqual({
      echoCancellation: true,
      noiseSuppression: true,
      autoGainControl: false,
      voiceIsolation: true,
      sampleRate: 48000,
      channelCount: 1,
    });
  });

  it("omits flags the browser does not report", () => {
    expect(JSON.parse(audioSettingsAttribute({ echoCancellation: true }))).toEqual({
      echoCancellation: true,
    });
  });
});
