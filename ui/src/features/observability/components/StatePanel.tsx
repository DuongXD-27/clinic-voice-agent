import { Inbox, LoaderCircle, TriangleAlert } from "lucide-react";

import { cx } from "../../../lib/cx";
import styles from "./StatePanel.module.css";

interface Props {
  kind: "loading" | "empty" | "error";
  title: string;
  detail?: string;
}

const ICONS = { loading: LoaderCircle, empty: Inbox, error: TriangleAlert };

/** Khung trạng thái khi đang tải, không có dữ liệu hoặc lỗi — thay cho bảng/biểu đồ. */
export function StatePanel({ kind, title, detail }: Props) {
  const Icon = ICONS[kind];
  return (
    <div className={cx(styles.panel, styles[kind])} role={kind === "error" ? "alert" : "status"}>
      <Icon className={styles.icon} aria-hidden />
      <div>
        <strong>{title}</strong>
        {detail && <p>{detail}</p>}
      </div>
    </div>
  );
}
