import { Room, RoomEvent, Track } from "livekit-client";
import { useCallback, useEffect, useReducer, useRef, type Dispatch, type RefObject } from "react";

import { requestToken } from "./api";
import { toTokenRequest, validateConfig, type LiveKitConfig } from "./model/config";
import { initialSession, liveKitReducer, type LiveKitAction } from "./model/session";
import { parseTranscript, TRANSCRIPT_TOPIC } from "./model/transcript";

/**
 * Một cuộc gọi LiveKit từ trình duyệt: lấy token, vào room, bật mic, phát audio của bot vào
 * `audio`. Mọi sự kiện Room đi qua reducer; rời trang thì tự ngắt kết nối.
 */
export function useLiveKitCall(audio: RefObject<HTMLAudioElement | null>) {
  const [session, dispatch] = useReducer(liveKitReducer, initialSession);
  const roomRef = useRef<Room | null>(null);

  const connect = useCallback(
    async (config: LiveKitConfig) => {
      const invalid = validateConfig(config);
      if (invalid) {
        dispatch({ type: "notice", notice: { tone: "error", text: invalid } });
        return;
      }
      dispatch({ type: "connecting", step: "Đang lấy token…" });
      try {
        const { url, token, room_name: roomName } = await requestToken(toTokenRequest(config));
        const room = new Room();
        roomRef.current = room;
        subscribe(room, dispatch, audio);

        dispatch({ type: "connecting", step: "Đang vào room…" });
        await room.connect(url, token);
        await room.startAudio();
        dispatch({ type: "connecting", step: "Đang bật microphone…" });
        await room.localParticipant.setMicrophoneEnabled(true);
        dispatch({
          type: "connected",
          roomName,
          botPresent: room.remoteParticipants.size > 0,
          at: Date.now(),
        });
      } catch (error) {
        // Bỏ listener trước khi ngắt để sự kiện Disconnected không ghi đè thông báo lỗi.
        const room = roomRef.current;
        roomRef.current = null;
        room?.removeAllListeners();
        void room?.disconnect();
        dispatch({ type: "failed", message: describe(error), at: Date.now() });
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

  /** Trình duyệt chặn autoplay: chỉ phát được sau một thao tác của người dùng. */
  const resumeAudio = useCallback(async () => {
    await roomRef.current?.startAudio();
  }, []);

  useEffect(
    () => () => {
      const room = roomRef.current;
      roomRef.current = null;
      room?.removeAllListeners();
      void room?.disconnect();
    },
    [],
  );

  return { session, connect, toggleMic, disconnect, resumeAudio };
}

function subscribe(
  room: Room,
  dispatch: Dispatch<LiveKitAction>,
  audio: RefObject<HTMLAudioElement | null>,
) {
  room
    .on(RoomEvent.TrackSubscribed, (track) => {
      if (track.kind === Track.Kind.Audio && audio.current) track.attach(audio.current);
    })
    .on(RoomEvent.ParticipantConnected, () => {
      dispatch({ type: "botPresence", present: true, at: Date.now() });
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
      if (topic !== TRANSCRIPT_TOPIC) return;
      const line = parseTranscript(payload);
      if (line) dispatch({ type: "transcript", line, at: Date.now() });
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

function describe(error: unknown): string {
  // So theo name, không instanceof DOMException (lỗi có thể đến từ realm khác).
  if (error instanceof Error && error.name === "NotAllowedError") {
    return "Trình duyệt không cho dùng microphone. Cho phép quyền microphone rồi thử lại.";
  }
  return error instanceof Error ? error.message : "Lỗi không xác định.";
}
