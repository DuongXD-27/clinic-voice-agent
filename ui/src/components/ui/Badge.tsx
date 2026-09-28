import type { ReactNode } from "react";

import { cx } from "../../lib/cx";
import styles from "./Badge.module.css";

export type Tone = "neutral" | "brand" | "success" | "warning" | "danger" | "info";

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={cx(styles.badge, styles[tone])}>{children}</span>;
}
