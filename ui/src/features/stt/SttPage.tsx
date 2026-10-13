import { Mic, Square } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { PageHeader } from "../../components/layout/PageHeader";
import { Segmented } from "../../components/ui/Segmented";
import { StatusIndicator } from "../../components/ui/StatusIndicator";
import { cx } from "../../lib/cx";
import { ASR_LABELS } from "../livekit/model/config";
import {
  describeStatus,
  describeTurn,
  STT_ASR_CHOICES,
  type SttAsr,
  type SttSession,
} from "./model/stt";
import styles from "./SttPage.module.css";
import { useSttSession } from "./useSttSession";

export function SttPage() {
  const [asr, setAsr] = useState<SttAsr>("gemini_live");
  const { session, start, stop } = useSttSession();
  const transcript = useRef<HTMLDivElement>(null);
  const active = session.phase !== "idle";

  useEffect(() => {
    const box = transcript.current;
    // jsdom không có scrollTo.
    if (box && typeof box.scrollTo === "function") {
      box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
    }
  }, [session.turns]);

  return (
    <>
      <PageHeader
        eyebrow="Thử STT · LiveKit"
        title="Nhận dạng giọng nói trực tiếp"
        description="Bấm Nói rồi nói vào microphone: chữ hiện ra theo từng lượt ngay khi model nhận dạng, qua đúng pipeline của cuộc gọi LiveKit (VAD, tăng âm, chốt lượt) — không có bot trả lời."
      />

      <div className={styles.controls}>
        <Segmented
          label="Model nhận dạng"
          name="stt-asr"
          value={asr}
          options={STT_ASR_CHOICES}
          onChange={setAsr}
          disabled={active}
        />
        <p className={styles.hint}>{workerNote(session, asr)}</p>
      </div>

      <section className={styles.stage} aria-label="Thử STT">
        <div className={styles.panel}>
          <div ref={transcript} className={styles.transcript} aria-live="polite">
            {session.turns.length === 0 ? (
              <p className={styles.placeholder}>{placeholder(session)}</p>
            ) : (
              session.turns.map((turn) => (
                <article key={turn.id} className={cx(styles.turn, styles[turn.status])}>
                  <p className={styles.text}>{turn.text || "…"}</p>
                  <p className={styles.meta}>{describeTurn(turn)}</p>
                </article>
              ))
            )}
          </div>
          {session.error && (
            <p role="alert" className={styles.error}>
              {session.error}
            </p>
          )}
          <footer className={styles.footer}>
            <div role="status" aria-label="Trạng thái">
              <StatusIndicator {...describeStatus(session)} />
            </div>
            {active ? (
              <button type="button" className={styles.pill} onClick={() => void stop()}>
                <Square aria-hidden />
                Kết thúc
              </button>
            ) : (
              <button type="button" className={styles.pill} onClick={() => void start(asr)}>
                <Mic aria-hidden />
                Nói
              </button>
            )}
          </footer>
        </div>
      </section>
    </>
  );
}

function placeholder(session: SttSession): string {
  if (session.phase === "connecting") return "Đang kết nối…";
  if (session.phase === "listening") return "Đang nghe — hãy nói gì đó.";
  return "Bấm Nói rồi nói vào microphone. Chữ sẽ hiện ra ở đây theo từng lượt.";
}

function workerNote(session: SttSession, asr: SttAsr): string {
  if (session.workerAsr === null) {
    return "Đổi model khi chưa nói. Lượt bị gạch là lượt model có nghe ra chữ nhưng pipeline bỏ (chỉ có từ đệm…).";
  }
  const used = ASR_LABELS[session.workerAsr] ?? session.workerAsr;
  return session.workerAsr === asr
    ? `Worker đang dùng: ${used}.`
    : `Worker đang dùng ${used} — KHÁC lựa chọn ${ASR_LABELS[asr] ?? asr}.`;
}
