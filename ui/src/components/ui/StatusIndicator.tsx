import { cx } from "../../lib/cx";
import styles from "./StatusIndicator.module.css";

export type StatusTone = "success" | "danger" | "warning" | "neutral";

interface Props {
  tone: StatusTone;
  label: string;
  /** Nhấp nháy khi đang chờ kết quả. */
  pulse?: boolean;
}

export function StatusIndicator({ tone, label, pulse = false }: Props) {
  return (
    <span className={styles.indicator}>
      <span className={cx(styles.dot, styles[tone], pulse && styles.pulse)} aria-hidden />
      <span className={styles.label}>{label}</span>
    </span>
  );
}
