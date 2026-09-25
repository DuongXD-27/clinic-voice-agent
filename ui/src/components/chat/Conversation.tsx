import { Bot, UserRound } from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import { cx } from "../../lib/cx";
import styles from "./Conversation.module.css";

/** Một dòng hội thoại; dùng chung cho cuộc gọi HTTP và LiveKit. */
export interface ChatMessage {
  id: string;
  role: "bot" | "caller";
  text: string;
  /** Dòng phụ dưới bong bóng: lượt, state, nguồn trích xuất, độ tin cậy ASR… */
  meta: string;
  audioUrl?: string | null;
}

interface Props {
  messages: readonly ChatMessage[];
  /** Hiện khi chưa có dòng nào. */
  empty: ReactNode;
  /** Đang chờ bot trả lời: hiện bong bóng "đang trả lời". */
  pending?: boolean;
  /** Tin nhắn bot được tự phát audio (chỉ câu mới nhất). */
  autoPlayId?: string | null;
  onAutoplayBlocked?: () => void;
}

export function Conversation({
  messages,
  empty,
  pending = false,
  autoPlayId = null,
  onAutoplayBlocked,
}: Props) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const element = box.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [messages.length, pending]);

  return (
    <div ref={box} className={styles.conversation} aria-live="polite" aria-label="Hội thoại">
      {messages.length === 0 && !pending && <p className={styles.empty}>{empty}</p>}
      {messages.map((message) => (
        <MessageBubble
          key={message.id}
          message={message}
          autoPlay={message.id === autoPlayId}
          onAutoplayBlocked={onAutoplayBlocked}
        />
      ))}
      {pending && (
        <div className={cx(styles.row, styles.bot)}>
          <Avatar role="bot" />
          <div className={cx(styles.bubble, styles.typing)} aria-label="Bot đang trả lời">
            <span />
            <span />
            <span />
          </div>
        </div>
      )}
    </div>
  );
}

function MessageBubble({
  message,
  autoPlay,
  onAutoplayBlocked,
}: {
  message: ChatMessage;
  autoPlay: boolean;
  onAutoplayBlocked: (() => void) | undefined;
}) {
  return (
    <div className={cx(styles.row, styles[message.role])}>
      <Avatar role={message.role} />
      <div className={styles.content}>
        <div className={styles.bubble}>
          {message.text}
          {message.audioUrl && (
            <MessageAudio
              src={message.audioUrl}
              autoPlay={autoPlay}
              onBlocked={onAutoplayBlocked}
            />
          )}
        </div>
        <p className={styles.meta}>{message.meta}</p>
      </div>
    </div>
  );
}

function Avatar({ role }: { role: ChatMessage["role"] }) {
  const Icon = role === "bot" ? Bot : UserRound;
  return (
    <span className={styles.avatar} aria-hidden>
      <Icon />
    </span>
  );
}

/**
 * Tự phát câu bot mới nhất. Trình duyệt có thể chặn autoplay khi lượt xử lý lâu làm hết
 * "user activation" — khi đó báo người dùng bấm play thay vì im lặng.
 */
function MessageAudio({
  src,
  autoPlay,
  onBlocked,
}: {
  src: string;
  autoPlay: boolean;
  onBlocked: (() => void) | undefined;
}) {
  const audio = useRef<HTMLAudioElement>(null);
  useEffect(() => {
    const element = audio.current;
    if (!autoPlay || !element) return;
    Promise.resolve()
      .then(() => element.play())
      .catch(() => onBlocked?.());
  }, [autoPlay, src, onBlocked]);

  return <audio ref={audio} src={src} controls preload="auto" className={styles.audio} />;
}
