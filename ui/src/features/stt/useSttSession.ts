import { ConnectionState, Room, RoomEvent } from "livekit-client";
import { useCallback, useEffect, useReducer, useRef, type Dispatch } from "react";

import { requestToken } from "../livekit/api";
import { parseStatus, STATUS_TOPIC } from "../livekit/model/transcript";
import { describeError } from "../livekit/useLiveKitCall";
import {
  initialStt,
  parseSttMessage,
  STT_TOPIC,
  sttReducer,
  type SttAction,
  type SttAsr,
} from "./model/stt";

/** Attribute worker gắn cho chính nó (callbot.transports.livekit.worker.ASR_ATTRIBUTE). */
const WORKER_ASR_ATTRIBUTE = "asr_provider";
/**
 * Worker rời phòng mà không gửi được lỗi (job crash): chờ chừng này rồi mới báo. livekit-client
 * cũng phát ParticipantDisconnected cho mọi người khi tự kết nối lại toàn bộ (mạng chập chờn) —
 * khi đó worker quay lại / phòng chuyển sang Reconnecting trong lúc chờ.
 */
const WORKER_GONE_GRACE_MS = 3000;
const WORKER_GONE = "Worker đã rời phòng nên phiên thử dừng — xem log worker để biết lý do.";

/**
 * Một phiên thử STT: vào room LiveKit với `mode=stt`, bật mic; worker chạy đúng STTPipeline của
 * cuộc gọi (không có bot) và gửi chữ từng lượt về. Rời trang thì tự ngắt.
 */
export function useSttSession() {
  const [session, dispatch] = useReducer(sttReducer, initialStt);
  const roomRef = useRef<Room | null>(null);
  // Tăng khi rời trang / bấm kết thúc: lần connect đang dở biết mình đã bị huỷ.
  const attemptRef = useRef(0);

  const start = useCallback(async (asr: SttAsr) => {
    const attempt = ++attemptRef.current;
    const cancelled = () => attempt !== attemptRef.current;
    dispatch({ type: "connecting", step: "Đang lấy token…" });
    let room: Room | null = null;
    try {
      const { url, token } = await requestToken({ mode: "stt", asr_provider: asr });
      if (cancelled()) return;
      room = new Room();
      roomRef.current = room;
      const joined = room;
      subscribe(
        joined,
        dispatch,
        (message) => {
          // Phiên không thể tiếp tục (worker không chạy được ASR đã chọn, worker rời phòng, mất
          // micro): rời room và gỡ listener — room cũ còn kết nối thì sự kiện của nó (chữ,
          // Disconnected) lẫn vào phiên bấm Nói lại sau đó.
          attemptRef.current += 1;
          if (roomRef.current === joined) roomRef.current = null;
          joined.removeAllListeners();
          void joined.disconnect();
          dispatch({ type: "failed", message });
        },
        () => roomRef.current === joined,
      );
      dispatch({ type: "connecting", step: "Đang vào room…" });
      await room.connect(url, token);
      if (cancelled()) return;
      dispatch({ type: "connecting", step: "Đang bật microphone…" });
      await room.localParticipant.setMicrophoneEnabled(true);
      if (cancelled()) return;
      dispatch({ type: "connected", workerPresent: room.remoteParticipants.size > 0 });
    } catch (error) {
      if (cancelled()) return;
      roomRef.current = null;
      room?.removeAllListeners();
      void room?.disconnect();
      dispatch({ type: "failed", message: describeError(error) });
    } finally {
      if (cancelled() && room && roomRef.current !== room) {
        room.removeAllListeners();
        void room.disconnect();
      }
    }
  }, []);

  const stop = useCallback(async () => {
    attemptRef.current += 1;
    const room = roomRef.current;
    roomRef.current = null;
    if (room) {
      // Sự kiện Disconnected cập nhật state (cùng đường với khi server/mạng ngắt).
      await room.disconnect();
    } else {
      dispatch({ type: "disconnected" });
    }
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

  return { session, start, stop };
}

/** `isCurrent`: phiên này chưa bị người dùng kết thúc / thay bằng phiên mới. */
function subscribe(
  room: Room,
  dispatch: Dispatch<SttAction>,
  onFatal: (message: string) => void,
  isCurrent: () => boolean,
) {
  let goneTimer: ReturnType<typeof setTimeout> | undefined;
  room
    .on(RoomEvent.ParticipantConnected, () => {
      clearTimeout(goneTimer);
      dispatch({ type: "workerPresence", present: true });
    })
    .on(RoomEvent.ParticipantDisconnected, () => {
      const present = room.remoteParticipants.size > 0;
      dispatch({ type: "workerPresence", present });
      if (present || !isCurrent()) return;
      clearTimeout(goneTimer);
      goneTimer = setTimeout(() => {
        if (
          isCurrent() &&
          room.remoteParticipants.size === 0 &&
          room.state === ConnectionState.Connected
        ) {
          onFatal(WORKER_GONE);
        }
      }, WORKER_GONE_GRACE_MS);
    })
    .on(RoomEvent.ParticipantAttributesChanged, (changed, participant) => {
      const provider = changed[WORKER_ASR_ATTRIBUTE];
      if (provider && participant.identity !== room.localParticipant.identity) {
        dispatch({ type: "workerAsr", provider });
      }
    })
    .on(RoomEvent.DataReceived, (payload, _participant, _kind, topic) => {
      if (topic === STATUS_TOPIC) {
        const message = parseStatus(payload);
        if (message) onFatal(message);
        return;
      }
      if (topic !== STT_TOPIC) return;
      const message = parseSttMessage(payload);
      if (message) dispatch({ type: "message", message });
    })
    .on(RoomEvent.Disconnected, () => {
      clearTimeout(goneTimer);
      dispatch({ type: "disconnected" });
    })
    .on(RoomEvent.MediaDevicesError, (error) => {
      onFatal(`Không truy cập được microphone: ${error.message}`);
    });
}
