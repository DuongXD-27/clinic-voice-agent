import { Bot, MicOff, UserRound } from "lucide-react";
import type { ReactNode } from "react";

import { cx } from "../../../lib/cx";
import type { LiveKitSession } from "../model/session";
import styles from "./Participants.module.css";

type Props = Pick<LiveKitSession, "phase" | "botPresent" | "micEnabled" | "speaking">;

/** Hai ô người tham gia; viền sáng khi đang nói (ActiveSpeakersChanged của LiveKit). */
export function Participants({ phase, botPresent, micEnabled, speaking }: Props) {
  const inCall = phase === "connected" || phase === "reconnecting";
  return (
    <div className={styles.participants}>
      <Tile
        icon={<Bot />}
        name="Bot Vinmec"
        status={botStatus(inCall, botPresent, speaking.bot)}
        speaking={inCall && speaking.bot}
        dim={!inCall || !botPresent}
      />
      <Tile
        icon={<UserRound />}
        name="Bạn"
        status={callerStatus(inCall, micEnabled, speaking.caller)}
        speaking={inCall && micEnabled && speaking.caller}
        dim={!inCall}
        muted={inCall && !micEnabled}
      />
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

interface TileProps {
  icon: ReactNode;
  name: string;
  status: string;
  speaking: boolean;
  dim: boolean;
  muted?: boolean;
}

function Tile({ icon, name, status, speaking, dim, muted = false }: TileProps) {
  return (
    <div
      className={cx(styles.tile, speaking && styles.speaking, dim && styles.dim)}
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
      <strong>{name}</strong>
      <span className={styles.status}>{status}</span>
    </div>
  );
}
