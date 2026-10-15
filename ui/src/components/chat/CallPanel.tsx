import type { ReactNode } from "react";

import { cx } from "../../lib/cx";
import { Card } from "../ui/Card";
import { Notice, type NoticeTone } from "../ui/Notice";
import { StatusIndicator, type StatusTone } from "../ui/StatusIndicator";
import { CallButton, type CallPhase } from "./CallButton";
import styles from "./CallPanel.module.css";
import { CallStatus } from "./CallStatus";
import { Conversation, type ChatMessage } from "./Conversation";

interface Props {
  /** Dòng trạng thái cạnh nút gọi (đang gọi, đang kết nối…). */
  status: { tone: StatusTone; label: string; pulse: boolean };
  phase: CallPhase;
  onStart: () => void;
  onEnd: () => void;
  /** State · Lượt · Outcome theo câu bot gần nhất. */
  metrics: { state: string | null; turnLabel: string; turn: number | null; outcome: string | null };
  notice: { tone: NoticeTone; text: string } | null;
  messages: readonly ChatMessage[];
  empty: ReactNode;
  pending?: boolean;
  autoPlayId?: string | null;
  onAutoplayBlocked?: () => void;
  /** Phần điều khiển dưới khung chat: ô nhập (HTTP) hoặc mic (LiveKit). */
  footer: ReactNode;
  className?: string;
}

/**
 * Khung cuộc gọi dùng chung cho trang HTTP và LiveKit: cùng vị trí nút gọi, cùng thanh trạng thái,
 * cùng khung hội thoại; chỉ phần điều khiển dưới cùng khác nhau.
 */
export function CallPanel({
  status,
  phase,
  onStart,
  onEnd,
  metrics,
  notice,
  messages,
  empty,
  pending = false,
  autoPlayId = null,
  onAutoplayBlocked,
  footer,
  className,
}: Props) {
  return (
    <Card className={cx(styles.panel, className)} aria-label="Cuộc gọi">
      <header className={styles.top}>
        <div role="status" aria-label="Trạng thái cuộc gọi" className={styles.status}>
          <StatusIndicator {...status} />
        </div>
        <CallButton phase={phase} onStart={onStart} onEnd={onEnd} />
      </header>
      <CallStatus {...metrics} />
      {notice && (
        <div className={styles.notice}>
          <Notice tone={notice.tone}>{notice.text}</Notice>
        </div>
      )}
      <Conversation
        messages={messages}
        empty={empty}
        pending={pending}
        autoPlayId={autoPlayId}
        {...(onAutoplayBlocked ? { onAutoplayBlocked } : {})}
      />
      <div className={styles.footer}>{footer}</div>
    </Card>
  );
}
