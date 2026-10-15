import { useCallback, useReducer, useRef } from "react";

import type { Schemas } from "../../lib/api/types";
import { CallApiError, sendTurn, startCall, uploadAudio, type Tracked } from "./api";
import {
  callReducer,
  initialSession,
  type CallAction,
  type Notice,
  type Reply,
} from "./model/callMachine";
import { toStartRequest, validateConfig, type CallConfig } from "./model/config";
import { describeFailure } from "./model/format";

/** Lượt im lặng mô phỏng của harness (contract Phụ lục A: silence_ms > 0). */
export const SILENCE_MS = 2000;

export type TurnInput =
  { kind: "text"; text: string } | { kind: "silence" } | { kind: "audio"; wav: Blob };

interface TurnTarget {
  callId: string;
  turn: number;
}

/**
 * Nối reducer cuộc gọi với API. Mỗi lần gác máy / reset tăng `generation`: response của cuộc gọi
 * cũ đến muộn bị bỏ, không lẫn vào cuộc gọi mới. API key lấy từ phiên đăng nhập (lib/auth).
 */
export function useCallSession() {
  const [session, dispatch] = useReducer(callReducer, initialSession);
  const generation = useRef(0);

  const guarded = useCallback(<T>(run: (isCurrent: () => boolean) => Promise<T>): Promise<T> => {
    const mine = generation.current;
    return run(() => mine === generation.current);
  }, []);

  const start = useCallback(
    (config: CallConfig) =>
      guarded(async (isCurrent) => {
        const invalid = validateConfig(config);
        if (invalid) {
          dispatch({ type: "notice", notice: { tone: "error", text: invalid } });
          return;
        }
        dispatch({ type: "start" });
        try {
          const request = toStartRequest(config);
          const result = await startCall(request);
          if (!isCurrent()) return;
          const { utterance, audio_url, state } = result.data;
          dispatch({
            type: "started",
            callId: request.call_id,
            reply: toReply(result, utterance, audio_url, state),
          });
        } catch (error) {
          if (isCurrent()) dispatch(failure(error));
        }
      }),
    [guarded],
  );

  /** Trả response của lượt khi thành công (để trang xoá ô nhập, tải lại dữ liệu), null nếu lỗi. */
  const send = useCallback(
    (input: TurnInput, { callId, turn }: TurnTarget) =>
      guarded(async (isCurrent): Promise<Schemas["TurnResponse"] | null> => {
        dispatch({ type: "turnSent" });
        try {
          let audioUrl: string | null = null;
          if (input.kind === "audio") {
            audioUrl = (await uploadAudio(callId, turn, input.wav)).data.audio_url;
            if (!isCurrent()) return null;
          }
          const body: Schemas["TurnRequest"] = {
            turn,
            text: input.kind === "text" ? input.text : null,
            audio_url: audioUrl,
            silence_ms: input.kind === "silence" ? SILENCE_MS : 0,
          };
          const result = await sendTurn(callId, body);
          if (!isCurrent()) return null;
          const { utterance, audio_url, state, ended, outcome } = result.data;
          dispatch({
            type: "turnDone",
            turn,
            caller: { text: callerText(input), audioUrl },
            reply: toReply(result, utterance, audio_url, state),
            ended,
            outcome: outcome ?? null,
          });
          return result.data;
        } catch (error) {
          if (isCurrent()) dispatch(failure(error));
          return null;
        }
      }),
    [guarded],
  );

  const reset = useCallback(() => {
    generation.current += 1;
    dispatch({ type: "reset" });
  }, []);

  /** Gác máy phía trình duyệt: giữ hội thoại để xem lại, bỏ response của lượt đang chờ. */
  const hangup = useCallback(() => {
    generation.current += 1;
    dispatch({ type: "hangup" });
  }, []);

  const notify = useCallback((notice: Notice | null) => {
    dispatch({ type: "notice", notice });
  }, []);

  return { session, start, send, reset, hangup, notify };
}

function toReply(
  result: Tracked<unknown>,
  utterance: string,
  audioUrl: string | null,
  state: Reply["state"],
): Reply {
  return {
    utterance,
    audioUrl,
    state,
    debug: result.debug,
    elapsedMs: result.elapsedMs,
    exchange: result.exchange,
  };
}

function callerText(input: TurnInput): string {
  switch (input.kind) {
    case "text":
      return input.text;
    case "silence":
      return `(im lặng ${SILENCE_MS / 1000} giây)`;
    case "audio":
      return "(ghi âm)";
  }
}

function failure(error: unknown): CallAction {
  if (error instanceof CallApiError) {
    return {
      type: "failed",
      message: describeFailure(error.code, error.message),
      exchange: error.exchange,
    };
  }
  const message = error instanceof Error ? error.message : "Lỗi không xác định.";
  return { type: "failed", message, exchange: null };
}
