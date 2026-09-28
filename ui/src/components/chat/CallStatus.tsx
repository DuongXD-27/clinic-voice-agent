import { outcomeTone } from "../../lib/outcome";
import { Badge } from "../ui/Badge";
import styles from "./CallStatus.module.css";

interface Props {
  /** State của bot sau lượt gần nhất. */
  state: string | null;
  /** Nhãn cột lượt: "Lượt tiếp theo" (HTTP) hoặc "Lượt" (LiveKit). */
  turnLabel: string;
  turn: number | null;
  outcome: string | null;
}

/** Dải State · Lượt · Outcome phía trên khung hội thoại. */
export function CallStatus({ state, turnLabel, turn, outcome }: Props) {
  return (
    <dl className={styles.status}>
      <div>
        <dt>State</dt>
        <dd>{state ?? "—"}</dd>
      </div>
      <div>
        <dt>{turnLabel}</dt>
        <dd>{turn ?? "—"}</dd>
      </div>
      <div>
        <dt>Outcome</dt>
        <dd>{outcome ? <Badge tone={outcomeTone(outcome)}>{outcome}</Badge> : "—"}</dd>
      </div>
    </dl>
  );
}
