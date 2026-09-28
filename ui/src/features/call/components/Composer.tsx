import { Mic, Send, Square, VolumeX } from "lucide-react";
import type { Ref } from "react";

import { Button } from "../../../components/ui/Button";
import { Textarea } from "../../../components/ui/Form";
import { cx } from "../../../lib/cx";
import type { RecorderState } from "../../../lib/audio/useRecorder";
import type { Mode } from "../model/config";
import styles from "./Composer.module.css";

interface Props {
  mode: Mode;
  /** Cuộc gọi đang mở và không chờ lượt nào. */
  enabled: boolean;
  busy: boolean;
  text: string;
  onTextChange: (value: string) => void;
  textRef: Ref<HTMLTextAreaElement>;
  recorder: RecorderState;
  onRecordToggle: () => void;
  onSend: () => void;
  onSilence: () => void;
  silenceSeconds: number;
}

export function Composer({
  mode,
  enabled,
  busy,
  text,
  onTextChange,
  textRef,
  recorder,
  onRecordToggle,
  onSend,
  onSilence,
  silenceSeconds,
}: Props) {
  const recording = recorder.status === "recording";
  const hasInput = mode === "text" ? text.trim() !== "" : recorder.status === "ready";

  return (
    <div className={styles.composer}>
      {mode === "text" ? (
        <Textarea
          ref={textRef}
          aria-label="Lời người gọi"
          placeholder={
            enabled ? "Nhập câu người gọi nói… (Enter để gửi)" : "Bắt đầu cuộc gọi để nhập"
          }
          value={text}
          disabled={!enabled}
          onChange={(event) => {
            onTextChange(event.target.value);
          }}
          onKeyDown={(event) => {
            if (event.key === "Enter" && !event.shiftKey) {
              event.preventDefault();
              if (enabled && hasInput) onSend();
            }
          }}
        />
      ) : (
        <RecordBox recorder={recorder} />
      )}

      <div className={styles.actions}>
        {mode === "audio" && (
          <Button
            variant={recording ? "danger" : "secondary"}
            icon={recording ? <Square /> : <Mic />}
            disabled={!enabled}
            onClick={onRecordToggle}
          >
            {recording ? "Dừng ghi" : recorder.status === "ready" ? "Ghi lại" : "Ghi âm"}
          </Button>
        )}
        <Button icon={<VolumeX />} disabled={!enabled || recording} onClick={onSilence}>
          Im lặng {silenceSeconds} giây
        </Button>
        <Button
          variant="primary"
          icon={<Send />}
          loading={busy}
          disabled={!enabled || !hasInput || recording}
          onClick={onSend}
          className={styles.send}
        >
          Gửi lượt
        </Button>
      </div>
    </div>
  );
}

function RecordBox({ recorder }: { recorder: RecorderState }) {
  const title =
    recorder.status === "recording"
      ? "Đang ghi âm…"
      : recorder.status === "ready"
        ? `WAV ${(recorder.blob.size / 1024).toFixed(1)} KiB · ${recorder.durationS.toFixed(1)} giây`
        : "Chưa có bản ghi";
  const hint =
    recorder.status === "recording"
      ? `Mic ${recorder.inputRate} Hz → PCM16 mono 16 kHz`
      : recorder.status === "ready"
        ? "Nghe lại rồi bấm Gửi lượt để upload và gọi API."
        : "Bấm Ghi âm và cho phép truy cập microphone.";

  return (
    <div className={cx(styles.record, recorder.status === "recording" && styles.recording)}>
      <span className={styles.dot} aria-hidden />
      <div className={styles.recordText}>
        <strong>{title}</strong>
        <small>{hint}</small>
      </div>
      {recorder.status === "ready" && (
        <audio
          src={recorder.url}
          controls
          className={styles.preview}
          aria-label="Nghe lại bản ghi"
        />
      )}
    </div>
  );
}
