import { Bot, Mic, MicOff, UserRound, Volume2 } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "../../../components/ui/Button";
import { cx } from "../../../lib/cx";
import type { LiveKitSession } from "../model/session";
import styles from "./VoiceDock.module.css";

type Props = Pick<
  LiveKitSession,
  "phase" | "botPresent" | "micEnabled" | "speaking" | "audioBlocked"
> & {
  onToggleMic: () => void;
  onResumeAudio: () => void;
};

/**
 * Chân khung cuộc gọi LiveKit (vị trí ô nhập của trang HTTP): ai đang nói — vòng sáng theo
 * ActiveSpeakersChanged — và nút mic / bật âm thanh.
 */
export function VoiceDock({
  phase,
  botPresent,
  micEnabled,
  speaking,
  audioBlocked,
  onToggleMic,
  onResumeAudio,
}: Props) {
  const inCall = phase === "connected" || phase === "reconnecting";
  return (
    <div className={styles.dock}>
      <div className={styles.speakers}>
        <Speaker
          icon={<Bot />}
          name="Bot"
          status={botStatus(inCall, botPresent, speaking.bot)}
          speaking={inCall && speaking.bot}
          dim={!inCall || !botPresent}
        />
        <Speaker
          icon={<UserRound />}
          name="Bạn"
          status={callerStatus(inCall, micEnabled, speaking.caller)}
          speaking={inCall && micEnabled && speaking.caller}
          dim={!inCall}
          muted={inCall && !micEnabled}
        />
      </div>
      {inCall ? (
        <div className={styles.controls}>
          {audioBlocked && (
            <Button icon={<Volume2 />} onClick={onResumeAudio}>
              Bật âm thanh
            </Button>
          )}
          <Button
            variant={micEnabled ? "secondary" : "danger"}
            icon={micEnabled ? <MicOff /> : <Mic />}
            onClick={onToggleMic}
          >
            {micEnabled ? "Tắt mic" : "Bật mic"}
          </Button>
        </div>
      ) : (
        <p className={styles.hint}>Trình duyệt sẽ xin quyền microphone khi bắt đầu.</p>
      )}
    </div>
  );
}

function botStatus(inCall: boolean, present: boolean, talking: boolean): string {
  if (!inCall) return "Chưa vào phòng";
  if (!present) return "Đang chờ bot vào phòng…";
  return talking ? "Đang nói" : "Đang nghe";
}

function callerStatus(inCall: boolean, micEnabled: boolean, talking: boolean): string {
  if (!inCall) return "Chưa kết nối";
  if (!micEnabled) return "Đã tắt mic";
  return talking ? "Đang nói" : "Mic đang bật";
}

interface SpeakerProps {
  icon: ReactNode;
  name: string;
  status: string;
  speaking: boolean;
  dim: boolean;
  muted?: boolean;
}

function Speaker({ icon, name, status, speaking, dim, muted = false }: SpeakerProps) {
  return (
    <div
      className={cx(styles.speaker, speaking && styles.speaking, dim && styles.dim)}
      aria-label={`${name}: ${status}`}
    >
      <span className={styles.avatar} aria-hidden>
        {icon}
        {muted && (
          <span className={styles.muted}>
            <MicOff />
          </span>
        )}
      </span>
      <span className={styles.text}>
        <strong>{name}</strong>
        <small>{status}</small>
      </span>
    </div>
  );
}
