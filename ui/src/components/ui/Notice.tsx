import { CircleAlert, CircleCheck, Info } from "lucide-react";
import type { ReactNode } from "react";

import { cx } from "../../lib/cx";
import styles from "./Notice.module.css";

export type NoticeTone = "info" | "success" | "warning" | "error";

const ICONS = { info: Info, success: CircleCheck, warning: CircleAlert, error: CircleAlert };

/** Thông báo một dòng. Lỗi dùng role="alert" để trình đọc màn hình đọc ngay. */
export function Notice({ tone = "info", children }: { tone?: NoticeTone; children: ReactNode }) {
  const Icon = ICONS[tone];
  return (
    <p className={cx(styles.notice, styles[tone])} role={tone === "error" ? "alert" : "status"}>
      <Icon aria-hidden />
      <span>{children}</span>
    </p>
  );
}
