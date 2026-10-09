/** Attribute gửi lên worker (AUDIO_SETTINGS_ATTRIBUTE trong call_bridge.py). */
export const AUDIO_SETTINGS_ATTRIBUTE = "audio.settings";

const FLAGS = [
  "echoCancellation",
  "noiseSuppression",
  "autoGainControl",
  "voiceIsolation",
] as const;
const NUMBERS = ["sampleRate", "channelCount"] as const;

/**
 * Thiết lập mic trình duyệt THỰC SỰ áp dụng (`MediaStreamTrack.getSettings()`), không phải cái
 * đã yêu cầu: `voiceIsolation` tuỳ trình duyệt có hỗ trợ không. Chỉ giữ cờ và số — không có
 * deviceId hay nhãn thiết bị.
 */
export function audioSettingsAttribute(settings: MediaTrackSettings): string {
  const source = settings as Record<string, unknown>;
  const picked: Record<string, boolean | number> = {};
  for (const key of FLAGS) {
    if (typeof source[key] === "boolean") picked[key] = source[key];
  }
  for (const key of NUMBERS) {
    if (typeof source[key] === "number") picked[key] = source[key];
  }
  return JSON.stringify(picked);
}
