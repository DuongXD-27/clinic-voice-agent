import { cx } from "../../../lib/cx";
import type { LogEntry } from "../model/session";
import styles from "./EventLog.module.css";

const TIME = new Intl.DateTimeFormat("vi-VN", { timeStyle: "medium" });

export function EventLog({ entries }: { entries: readonly LogEntry[] }) {
  if (entries.length === 0) {
    return (
      <p className={styles.empty}>Chưa có sự kiện. Bắt đầu cuộc gọi để xem diễn biến kết nối.</p>
    );
  }
  return (
    <ol className={styles.log} aria-label="Nhật ký cuộc gọi">
      {[...entries].reverse().map((entry) => (
        <li key={entry.id} className={cx(styles.entry, styles[entry.tone])}>
          <time dateTime={new Date(entry.at).toISOString()}>{TIME.format(entry.at)}</time>
          <span>{entry.text}</span>
        </li>
      ))}
    </ol>
  );
}
