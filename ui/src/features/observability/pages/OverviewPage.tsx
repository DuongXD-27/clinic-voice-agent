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
      {data.extended && (
        <section className={styles.stack} aria-label="Model và chi phí">
          <h2>Model, âm thanh và chi phí</h2>
          <dl className={styles.summary}>
            <div>
              <dt>Cuộc gọi</dt>
              <dd>{data.extended.call_count}</dd>
            </div>
            <div>
              <dt>LLM p95</dt>
              <dd>{data.extended.llm_latency.p95_ms?.toFixed(0) ?? "—"} ms</dd>
            </div>
            <div>
              <dt>LLM model call p95</dt>
              <dd>
                {data.extended.llm_model_call_latency?.p95_ms == null
                  ? "N/A"
                  : `${data.extended.llm_model_call_latency.p95_ms.toFixed(0)} ms`}{" "}
                ({data.extended.llm_model_call_latency?.count ?? 0}/
                {data.extended.llm_latency.count} measured)
              </dd>
            </div>
            <div>
              <dt>Turn p90</dt>
              <dd>{data.extended.turn_latency_p90_ms?.toFixed(0) ?? "—"} ms</dd>
            </div>
            <div>
              <dt>STT provider p95 (batch)</dt>
              <dd>{data.extended.stt_provider_latency?.p95_ms?.toFixed(0) ?? "N/A"} ms</dd>
            </div>
            <div>
              <dt>STT first partial p95</dt>
              <dd>{data.extended.stt_first_partial?.p95_ms?.toFixed(0) ?? "N/A"} ms</dd>
            </div>
            <div>
              <dt>STT final từ lúc bắt đầu nói p95</dt>
              <dd>{data.extended.stt_final_latency?.p95_ms?.toFixed(0) ?? "N/A"} ms</dd>
            </div>
            <div>
              <dt>TTS TTFA p95</dt>
              <dd>{data.extended.ttfa.p95_ms?.toFixed(0) ?? "—"} ms</dd>
            </div>
            <div>
              <dt>STT confidence TB</dt>
              <dd>{data.extended.stt.confidence_mean?.toFixed(2) ?? "—"}</dd>
            </div>
            <div>
              <dt>TTS ký tự</dt>
              <dd>{data.extended.tts.characters}</dd>
            </div>
            <div>
              <dt>TTS fallback / ngắt</dt>
              <dd>
                {data.extended.tts.fallback_count} / {data.extended.tts.interrupted_count}
              </dd>
            </div>
            <div>
              <dt>Clinic retry / conflict</dt>
              <dd>
                {data.extended.clinic.retry_count} / {data.extended.clinic.version_conflicts}
              </dd>
            </div>
            <div>
              <dt>Lỗi kỹ thuật</dt>
              <dd>
                {Object.values(data.extended.technical_errors.by_component).reduce(
                  (sum, count) => sum + count,
                  0,
                )}
              </dd>
            </div>
            <div>
              <dt>Evaluation scores</dt>
              <dd>
                {data.extended.evaluation.score_count} (
                {data.extended.evaluation.local_only_count ?? 0} local only)
              </dd>
            </div>
            <div>
              <dt>Chi phí đã biết (USD)</dt>
              <dd>
                {data.extended.cost.cost_known
                  ? `${data.extended.cost.known_cost_total.toFixed(6)}${data.extended.cost.cost_complete ? " · đầy đủ" : " · một phần"}`
                  : "N/A · chưa có giá hoặc usage"}
              </dd>
            </div>
          </dl>
          {data.extended.tts.providers.length > 0 && (
            <p className={styles.helper}>
              TTS thực tế:{" "}
              {data.extended.tts.providers
                .map((row) => `${row.provider}/${row.voice} (${row.count})`)
                .join(", ")}
            </p>
          )}
          {data.extended.models.length > 0 && (
            <table>
              <caption>LLM usage theo model</caption>
              <thead>
                <tr>
                  <th>Provider / Model</th>
                  <th>Calls</th>
                  <th>OK</th>
                  <th>Timeout</th>
                  <th>Error</th>
                  <th>Invalid</th>
                  <th>Input tokens</th>
                  <th>Output tokens</th>
                </tr>
              </thead>
              <tbody>
                {data.extended.models.map((row) => (
                  <tr key={`${row.provider}/${row.model}`}>
                    <td>
                      {row.provider} / {row.model}
                    </td>
                    <td>{row.calls}</td>
                    <td>{row.ok}</td>
                    <td>{row.timeout}</td>
                    <td>{row.error}</td>
                    <td>{row.invalid}</td>
                    <td>{row.input_tokens}</td>
                    <td>{row.output_tokens}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
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
