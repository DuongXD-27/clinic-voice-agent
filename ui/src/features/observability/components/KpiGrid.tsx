import { cx } from "../../../lib/cx";
import type { KpiCard, Metric } from "../model/overview";
import styles from "./KpiGrid.module.css";

interface Props {
  cards: readonly KpiCard[];
  selected: Metric | null;
  onSelect: (metric: Metric) => void;
}

/** Thẻ KPI bấm được: chọn để mở chi tiết, bấm lại để đóng. */
export function KpiGrid({ cards, selected, onSelect }: Props) {
  return (
    <div className={styles.grid}>
      {cards.map((card) => (
        <button
          key={card.metric}
          type="button"
          className={cx(
            styles.card,
            !card.hasData && styles.noData,
            card.metric === selected && styles.selected,
          )}
          aria-pressed={card.metric === selected}
          onClick={() => {
            onSelect(card.metric);
          }}
        >
          <span className={styles.label}>{card.label}</span>
          <strong className={styles.value}>{card.value}</strong>
          <span className={styles.context}>{card.context}</span>
        </button>
      ))}
    </div>
  );
}
