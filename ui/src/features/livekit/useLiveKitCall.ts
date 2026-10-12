import { Room, RoomEvent, Track } from "livekit-client";
import { useCallback, useEffect, useReducer, useRef, type Dispatch, type RefObject } from "react";

import { requestToken } from "./api";
import { AUDIO_SETTINGS_ATTRIBUTE, audioSettingsAttribute } from "./model/audioSettings";
import { toTokenRequest, validateConfig, type LiveKitConfig } from "./model/config";
import {
  initialSession,
  liveKitReducer,
  type LiveKitAction,
  type LiveKitSession,
} from "./model/session";
import {
  parseNBest,
  parseStatus,
  parseTranscript,
  STATUS_TOPIC,
  TRANSCRIPT_TOPIC,
} from "./model/transcript";

/** Attribute worker gắn cho bot (callbot.transports.livekit.worker.ASR_ATTRIBUTE). */
const BOT_ASR_ATTRIBUTE = "asr_provider";

/**
 * Một cuộc gọi LiveKit từ trình duyệt: lấy token, vào room, bật mic, phát audio của bot vào
 * `audio`. Mọi sự kiện Room đi qua reducer; rời trang thì tự ngắt kết nối.
 */
export function useLiveKitCall(audio: RefObject<HTMLAudioElement | null>) {
  const [session, dispatch] = useReducer(liveKitReducer, initialSession);
  const roomRef = useRef<Room | null>(null);
  // Tăng khi rời trang: lần connect đang dở (chờ token, vào room, xin quyền mic) biết mình đã
  // bị huỷ, tự ngắt room thay vì để mic bật và bot nói tiếp trong một room không ai thấy.
  const attemptRef = useRef(0);

  const connect = useCallback(
    async (config: LiveKitConfig) => {
      const invalid = validateConfig(config);
      if (invalid) {
        dispatch({ type: "notice", notice: { tone: "error", text: invalid } });
        return;
      }
      const attempt = ++attemptRef.current;
      const cancelled = () => attempt !== attemptRef.current;
      dispatch({ type: "connecting", step: "Đang lấy token…" });
      let room: Room | null = null;
      try {
        const { url, token, room_name: roomName } = await requestToken(toTokenRequest(config));
        if (cancelled()) return;
        room = new Room();
        roomRef.current = room;
        const joined = room;
        subscribe(joined, dispatch, audio, (message) => {
          // Worker không mở được cuộc gọi (vd. lịch outbound không dùng được) và sẽ không nói
          // gì thêm: rời room, huỷ lần connect đang dở để nó không ghi đè thông báo lỗi.
          attemptRef.current += 1;
          if (roomRef.current === joined) roomRef.current = null;
          joined.removeAllListeners();
          void joined.disconnect();
          dispatch({ type: "failed", message, at: Date.now() });
        });

        dispatch({ type: "connecting", step: "Đang vào room…" });
        await room.connect(url, token);
        if (cancelled()) return;
        await room.startAudio();
        dispatch({ type: "connecting", step: "Đang bật microphone…" });
        await room.localParticipant.setMicrophoneEnabled(true);
        if (cancelled()) return;
        reportAudioSettings(room);
        dispatch({
          type: "connected",
          roomName,
          botPresent: room.remoteParticipants.size > 0,
          at: Date.now(),
          asr: config.asrProvider === "server" ? null : config.asrProvider,
        });
      } catch (error) {
        if (cancelled()) return;
        // Bỏ listener trước khi ngắt để sự kiện Disconnected không ghi đè thông báo lỗi.
        roomRef.current = null;
        room?.removeAllListeners();
        void room?.disconnect();
        dispatch({ type: "failed", message: describe(error), at: Date.now() });
      } finally {
        // Đã rời trang giữa chừng: cleanup có thể đã chạy trước khi room này được tạo.
        if (cancelled() && room) {
          room.removeAllListeners();
          void room.disconnect();
        }
      }
    },
    [audio],
  );

  const toggleMic = useCallback(async () => {
    const room = roomRef.current;
    if (!room) return;
    const enabled = !room.localParticipant.isMicrophoneEnabled;
    try {
      await room.localParticipant.setMicrophoneEnabled(enabled);
      if (enabled) reportAudioSettings(room);
      dispatch({ type: "micChanged", enabled, at: Date.now() });
    } catch (error) {
      dispatch({ type: "notice", notice: { tone: "error", text: describe(error) } });
    }
  }, []);

  const disconnect = useCallback(async () => {
    const room = roomRef.current;
    roomRef.current = null;
    // Sự kiện Disconnected cập nhật state (cùng đường với khi server/mạng ngắt).
    await room?.disconnect();
  }, []);

  const notify = useCallback((notice: LiveKitSession["notice"]) => {
    dispatch({ type: "notice", notice });
  }, []);

  /** Trình duyệt chặn autoplay: chỉ phát được sau một thao tác của người dùng. */
  const resumeAudio = useCallback(async () => {
    await roomRef.current?.startAudio();
  }, []);

  useEffect(
    () => () => {
      attemptRef.current += 1;
      const room = roomRef.current;
      roomRef.current = null;
      room?.removeAllListeners();
      void room?.disconnect();
    },
    [],
  );

  return { session, connect, toggleMic, disconnect, resumeAudio, notify };
}

function subscribe(
  room: Room,
  dispatch: Dispatch<LiveKitAction>,
  audio: RefObject<HTMLAudioElement | null>,
  onBotError: (message: string) => void,
) {
  room
    .on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Audio && audio.current) track.attach(audio.current);
    })
    .on(RoomEvent.ParticipantConnected, () => {
      dispatch({ type: "botPresence", present: true, at: Date.now() });
    })
    .on(RoomEvent.ParticipantAttributesChanged, (changed, participant) => {
      // Worker báo ASR dùng cho cuộc gọi — luôn đúng ASR đã chọn; không tạo được thì worker báo
      // lỗi qua STATUS_TOPIC và dừng, không đổi sang ASR khác.
      const provider = changed[BOT_ASR_ATTRIBUTE];
      if (provider && participant.identity !== room.localParticipant.identity) {
        dispatch({ type: "botAsr", provider, at: Date.now() });
      }
    })
    .on(RoomEvent.ParticipantDisconnected, () => {
      dispatch({ type: "botPresence", present: room.remoteParticipants.size > 0, at: Date.now() });
    })
    .on(RoomEvent.ActiveSpeakersChanged, (speakers) => {
      const local = room.localParticipant.identity;
      dispatch({
        type: "speakers",
        caller: speakers.some((participant) => participant.identity === local),
        bot: speakers.some((participant) => participant.identity !== local),
      });
    })
    .on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic === STATUS_TOPIC) {
        const message = parseStatus(payload);
        if (message) onBotError(message);
        return;
      }
      if (topic !== TRANSCRIPT_TOPIC) return;
      const line = parseTranscript(payload);
      if (line) {
        dispatch({ type: "transcript", line, at: Date.now() });
        return;
      }
      const update = parseNBest(payload);
      if (update) dispatch({ type: "nbest", update });
    })
    .on(RoomEvent.Reconnecting, () => {
      dispatch({ type: "reconnecting", at: Date.now() });
    })
    .on(RoomEvent.Reconnected, () => {
      dispatch({ type: "reconnected", at: Date.now() });
    })
    .on(RoomEvent.Disconnected, () => {
      dispatch({ type: "disconnected", at: Date.now() });
    })
    .on(RoomEvent.AudioPlaybackStatusChanged, () => {
      dispatch({ type: "audioBlocked", blocked: !room.canPlaybackAudio });
    })
    .on(RoomEvent.MediaDevicesError, (error) => {
      dispatch({
        type: "notice",
        notice: { tone: "error", text: `Không truy cập được microphone: ${error.message}` },
      });
    });
}

/**
 * Gửi worker thiết lập mic trình duyệt thật sự áp dụng (AEC/NS/AGC/voiceIsolation) để log đo
 * đầu vào. Chỉ phục vụ đo: lỗi ở đây không được làm hỏng cuộc gọi.
 */
function reportAudioSettings(room: Room) {
  try {
    const track = room.localParticipant.getTrackPublication(Track.Source.Microphone)?.track;
    const settings = track?.mediaStreamTrack.getSettings();
    if (!settings) return;
    void room.localParticipant
      .setAttributes({ [AUDIO_SETTINGS_ATTRIBUTE]: audioSettingsAttribute(settings) })
      .catch(() => undefined);
  } catch {
    // Không có track hoặc trình duyệt không hỗ trợ getSettings: bỏ qua.
  }
}

function describe(error: unknown): string {
  // So theo name, không instanceof DOMException (lỗi có thể đến từ realm khác).
  if (error instanceof Error && error.name === "NotAllowedError") {
    return "Trình duyệt không cho dùng microphone. Cho phép quyền microphone rồi thử lại.";
  }
  return error instanceof Error ? error.message : "Lỗi không xác định.";
}
