import { useCallback, useEffect, useRef, useState } from "react";

// no-inline: file nhỏ sẽ bị Vite nhúng thành data: URL, mà Safari không nạp worklet từ data: URL.
import workletUrl from "./recorder.worklet.js?url&no-inline";
import { encodeWav, mergeFloat32, resampleLinear } from "./wav";

/** Backend chuẩn hoá tiếp về 8 kHz; gửi 16 kHz để giữ chất lượng trước bước đó. */
const RECORDING_RATE = 16_000;
/** Chờ processor xác nhận dừng tối đa bấy nhiêu; quá thì dùng các khối đã nhận. */
const STOP_TIMEOUT_MS = 500;

export type RecorderState =
  | { status: "idle" }
  | { status: "recording"; inputRate: number }
  | { status: "ready"; blob: Blob; url: string; durationS: number };

interface Session {
  stream: MediaStream;
  context: AudioContext;
  source: MediaStreamAudioSourceNode;
  node: AudioWorkletNode;
  chunks: Float32Array[];
  startedAt: number;
}

/** Ghi mic thành WAV PCM16 mono qua AudioWorklet (xử lý trên luồng audio, không chặn UI). */
export function useRecorder() {
  const [state, setState] = useState<RecorderState>({ status: "idle" });
  const session = useRef<Session | null>(null);
  const previewUrl = useRef<string | null>(null);
  // Lần start đang chờ quyền mic / nạp worklet. Tăng `attempt` (clear, rời trang) để lần đó
  // tự tắt mic khi xong, thay vì để lại một stream không ai giữ.
  const starting = useRef(false);
  const attempt = useRef(0);

  const releasePreview = useCallback(() => {
    if (previewUrl.current) URL.revokeObjectURL(previewUrl.current);
    previewUrl.current = null;
  }, []);

  /** Ném lỗi nếu trình duyệt không hỗ trợ hoặc người dùng không cho dùng mic. */
  const start = useCallback(async () => {
    if (!("mediaDevices" in navigator)) {
      throw new Error("Trình duyệt không hỗ trợ thu microphone (cần HTTPS hoặc localhost).");
    }
    // Bấm Ghi âm lần hai khi hộp xin quyền còn mở: bỏ qua, không mở stream thứ hai.
    if (starting.current || session.current) return;
    starting.current = true;
    const mine = ++attempt.current;
    let stream: MediaStream;
    let context: AudioContext;
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
      });
      context = new AudioContext();
      try {
        await context.audioWorklet.addModule(workletUrl);
      } catch (error) {
        for (const track of stream.getTracks()) track.stop();
        void context.close();
        throw error;
      }
    } finally {
      starting.current = false;
    }
    if (mine !== attempt.current) {
      // clear() hoặc rời trang trong lúc chờ: tắt mic vừa mở.
      for (const track of stream.getTracks()) track.stop();
      void context.close();
      return;
    }
    const source = context.createMediaStreamSource(stream);
    // Không có output: node là điểm cuối nên vẫn được xử lý mà không phát ngược ra loa.
    const node = new AudioWorkletNode(context, "recorder", {
      numberOfInputs: 1,
      numberOfOutputs: 0,
      channelCount: 1,
    });
    const chunks: Float32Array[] = [];
    node.port.onmessage = (event: MessageEvent<unknown>) => {
      if (event.data instanceof Float32Array) chunks.push(event.data);
    };
    source.connect(node);

    session.current = { stream, context, source, node, chunks, startedAt: performance.now() };
    releasePreview();
    setState({ status: "recording", inputRate: context.sampleRate });
  }, [releasePreview]);

  const stop = useCallback(async () => {
    const finished = session.current;
    if (!finished) return;
    session.current = null;
    const durationS = (performance.now() - finished.startedAt) / 1000;

    await Promise.race([drain(finished), delay(STOP_TIMEOUT_MS)]);
    release(finished);

    const samples = resampleLinear(
      mergeFloat32(finished.chunks),
      finished.context.sampleRate,
      RECORDING_RATE,
    );
    const blob = new Blob([encodeWav(samples, RECORDING_RATE)], { type: "audio/wav" });
    const url = URL.createObjectURL(blob);
    previewUrl.current = url;
    setState({ status: "ready", blob, url, durationS });
  }, []);

  const clear = useCallback(() => {
    attempt.current += 1;
    if (session.current) release(session.current);
    session.current = null;
    releasePreview();
    setState({ status: "idle" });
  }, [releasePreview]);

  // Rời trang khi đang ghi: tắt mic và giải phóng URL preview.
  useEffect(
    () => () => {
      attempt.current += 1;
      if (session.current) release(session.current);
      session.current = null;
      releasePreview();
    },
    [releasePreview],
  );

  return { state, start, stop, clear };
}

/** Báo processor dừng và chờ các khối còn trên đường về. */
function drain({ node, chunks }: Session): Promise<void> {
  return new Promise((resolve) => {
    node.port.onmessage = (event: MessageEvent<unknown>) => {
      if (event.data instanceof Float32Array) chunks.push(event.data);
      else if (event.data === "stopped") resolve();
    };
    node.port.postMessage("stop");
  });
}

function release({ stream, context, source, node }: Session) {
  source.disconnect();
  node.port.onmessage = null;
  node.disconnect();
  for (const track of stream.getTracks()) track.stop();
  void context.close();
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
