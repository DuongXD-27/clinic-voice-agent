import type { Exchange } from "../model/callMachine";
import styles from "./DebugPanel.module.css";

export function DebugPanel({ exchange }: { exchange: Exchange | null }) {
  if (!exchange) return <p className={styles.empty}>Chưa có request.</p>;
  return (
    <pre className={styles.pre}>
      {[
        `${exchange.method} ${exchange.path}`,
        "",
        "REQUEST",
        JSON.stringify(exchange.request, null, 2),
        "",
        `RESPONSE ${exchange.status}`,
        JSON.stringify(exchange.response, null, 2),
      ].join("\n")}
    </pre>
  );
}
