import type { ReactNode } from "react";

import { Badge } from "../../../components/ui/Badge";
import type { ExtractionModel, TurnExtraction } from "../model/callMachine";
import {
  FIELD_LABELS,
  formatValue,
  highlightSpans,
  MODEL_STATUS,
  modelProviderLabel,
} from "../model/format";
import styles from "./ExtractionPanel.module.css";

/** Câu người gọi (tô sáng cụm đã trích), model đã đọc câu và bảng trường trích xuất của lượt gần nhất. */
export function ExtractionPanel({
  extraction,
  empty = "Chưa có lượt nào.",
}: {
  extraction: TurnExtraction | null;
  empty?: ReactNode;
}) {
  if (!extraction) return <p className={styles.empty}>{empty}</p>;

  const { turn, fields } = extraction;
  if (!fields) {
    return <p className={styles.empty}>Lượt {turn}: lượt này không qua bước trích xuất.</p>;
  }
  if (fields.silent) return <p className={styles.empty}>Lượt {turn}: im lặng, không trích xuất.</p>;

  return (
    <div className={styles.panel}>
      <p className={styles.sentence}>
        <span className={styles.turn}>Lượt {turn}</span>
        {highlightSpans(
          fields.transcript,
          fields.fields.map((field) => field.span),
        ).map((segment, index) =>
          segment.marked ? <mark key={index}>{segment.text}</mark> : segment.text,
        )}
      </p>
      <ModelLine model={fields.model} />
      {fields.fields.length === 0 ? (
        <p className={styles.empty}>Không trích được trường nào từ câu này.</p>
      ) : (
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Trường</th>
              <th scope="col">Giá trị</th>
              <th scope="col">Từ trong câu</th>
              <th scope="col">Nguồn</th>
            </tr>
          </thead>
          <tbody>
            {fields.fields.map((field) => (
              <tr key={field.field}>
                <td>{FIELD_LABELS[field.field] ?? field.field}</td>
                <td className={styles.value}>{formatValue(field.value)}</td>
                <td>{field.span ? `“${field.span}”` : "—"}</td>
                <td>{field.provenance ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}

/** Model nào đọc câu (Jev, OpenAI dự phòng…) hay chỉ luật — trường FALLBACK là do model này. */
function ModelLine({ model }: { model: ExtractionModel | null }) {
  if (!model) {
    return <p className={styles.model}>Model đọc câu: không gọi — chỉ dùng luật.</p>;
  }
  const status = model.status ? MODEL_STATUS[model.status] : undefined;
  return (
    <p className={styles.model}>
      Model đọc câu: <strong>{modelProviderLabel(model.provider)}</strong>{" "}
      <span className={styles.modelName}>{model.name}</span>
      {model.status && (
        <Badge tone={status?.tone ?? "neutral"}>{status?.label ?? model.status}</Badge>
      )}
      {model.backupFor && (
        <Badge tone="warning">dự phòng — {modelProviderLabel(model.backupFor)} lỗi</Badge>
      )}
    </p>
  );
}
