import { useSearchParams } from "react-router";

import { observabilityApi } from "../api";
import { KpiGrid } from "../components/KpiGrid";
import { StatePanel } from "../components/StatePanel";
import { formatCount, formatTimestamp } from "../model/format";
import { kpiCards, parseMetric, parseSlowThreshold, type Metric } from "../model/overview";
import { useQuery } from "../useQuery";
import { useObservability } from "./context";
import { MetricDetail } from "./MetricDetail";
import styles from "./pages.module.css";

export function OverviewPage() {
  const { range, window, windowKey } = useObservability();
  const [params, setParams] = useSearchParams();
  const metric = parseMetric(params.get("metric"));
  const slowThreshold = parseSlowThreshold(params.get("slow"));

  const overview = useQuery(`overview|${windowKey}|${String(slowThreshold)}`, (signal) =>
    observabilityApi.overview(window, slowThreshold, signal),
  );

  const update = (changes: Record<string, string | null>) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null) next.delete(key);
        else next.set(key, value);
      }
      return next;
    });
  };

  const toggleMetric = (selected: Metric) => {
    update({ metric: selected === metric ? null : selected });
  };

  if (overview.status === "loading") return <StatePanel kind="loading" title="Đang tải số liệu…" />;
  if (overview.status === "error") {
    return <StatePanel kind="error" title="Không tải được số liệu" detail={overview.message} />;
  }

  const data = overview.data;
  return (
    <div className={styles.page}>
      <p className={styles.meta} role="status">
        Khoảng {formatTimestamp(data.time_range.start)} → {formatTimestamp(data.time_range.end)} ·{" "}
        {formatCount(data.turn_count)} lượt · {formatCount(data.diagnostics.records_processed)} bản
        ghi trace
      </p>
      <KpiGrid cards={kpiCards(data)} selected={metric} onSelect={toggleMetric} />
      {metric ? (
        <MetricDetail
          metric={metric}
          data={data}
          range={range}
          window={window}
          windowKey={windowKey}
          slowThreshold={slowThreshold}
          onSlowThreshold={(value) => {
            update({ slow: String(value) });
          }}
          onClose={() => {
            update({ metric: null });
          }}
        />
      ) : (
        <p className={styles.helper}>Chọn một chỉ số để xem biểu đồ theo giờ và chi tiết.</p>
      )}
    </div>
  );
}
