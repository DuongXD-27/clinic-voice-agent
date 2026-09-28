import type { CallSession } from "../model/callMachine";
import { FIELD_LABELS, formatValue, highlightSpans } from "../model/format";
import styles from "./ExtractionPanel.module.css";

/** Câu người gọi (tô sáng cụm đã trích) và bảng trường trích xuất của lượt gần nhất. */
export function ExtractionPanel({ extraction }: { extraction: CallSession["extraction"] }) {
  if (!extraction) return <p className={styles.empty}>Chưa có lượt nào.</p>;

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
