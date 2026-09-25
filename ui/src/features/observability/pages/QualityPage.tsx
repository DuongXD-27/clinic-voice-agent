import { useSearchParams } from "react-router";

import { Segmented } from "../../../components/ui/Segmented";
import { observabilityApi } from "../api";
import { QualityReport } from "../components/QualityReport";
import { StatePanel } from "../components/StatePanel";
import { parseQuality, type QualitySettings } from "../model/quality";
import { useQuery } from "../useQuery";
import { useObservability } from "./context";
import styles from "./pages.module.css";

const COMPONENTS = [
  { value: "STT", label: "STT" },
  { value: "TTS", label: "TTS" },
] as const;
const VIEWS = [
  { value: "both", label: "Cả hai" },
  { value: "numbers", label: "Số liệu" },
  { value: "charts", label: "Biểu đồ" },
] as const;
const AGGREGATIONS = [
  { value: "call", label: "Theo cuộc gọi" },
  { value: "turn", label: "Theo lượt" },
] as const;

export function QualityPage() {
  const { range, window, windowKey } = useObservability();
  const [params, setParams] = useSearchParams();
  const settings = parseQuality(params);

  const quality = useQuery(
    `quality|${windowKey}|${settings.component}|${settings.aggregation}`,
    (signal) => observabilityApi.quality(window, settings.component, settings.aggregation, signal),
  );

  const update = (changes: Partial<QualitySettings>) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      for (const [key, value] of Object.entries(changes)) {
        if (value === null) next.delete(key);
        else next.set(key, value);
      }
      return next;
    });
  };

  return (
    <div className={styles.page}>
      <div className={styles.toolbar}>
        <Segmented
          label="Module"
          name="quality-component"
          value={settings.component}
          options={COMPONENTS}
          onChange={(component) => {
            update({ component, issue: null });
          }}
        />
        <Segmented
          label="Tổng hợp"
          name="quality-aggregation"
          value={settings.aggregation}
          options={AGGREGATIONS}
          onChange={(aggregation) => {
            update({ aggregation, issue: null });
          }}
        />
        <Segmented
          label="Hiển thị"
          name="quality-view"
          value={settings.view}
          options={VIEWS}
          onChange={(view) => {
            update({ view });
          }}
        />
      </div>
      {quality.status === "loading" && (
        <StatePanel kind="loading" title={`Đang tải chất lượng ${settings.component}…`} />
      )}
      {quality.status === "error" && (
        <StatePanel
          kind="error"
          title="Không tải được số liệu chất lượng"
          detail={quality.message}
        />
      )}
      {quality.status === "ready" && (
        <QualityReport
          data={quality.data}
          view={settings.view}
          issue={settings.issue}
          onIssue={(issue) => {
            update({ issue });
          }}
          range={range}
        />
      )}
    </div>
  );
}
