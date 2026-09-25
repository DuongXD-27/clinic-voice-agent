import { Badge } from "../../../components/ui/Badge";
import { cx } from "../../../lib/cx";
import { displayLabel, formatCount, formatDuration, formatTimestamp } from "../model/format";
import type { CallDetail, Stage, TurnExecution } from "../model/types";
import { DataTable } from "./DataTable";
import styles from "./ExecutionViews.module.css";
import { StatePanel } from "./StatePanel";
import { StatusBadge, TurnLink } from "./tables";

/** Các lượt của một cuộc gọi (kể cả lượt chạy lại), mỗi dòng mở được chi tiết lượt. */
export function CallExecutions({ data, range }: { data: CallDetail; range: number }) {
  if (data.executions.length === 0) {
    return (
      <StatePanel kind="empty" title="Trang này không có lượt nào" detail="Quay lại trang trước." />
    );
  }
  return (
    <DataTable
      label="Các lượt của cuộc gọi"
      rows={data.executions}
      rowKey={(item) => item.trace_id}
      columns={[
        {
          header: "Lượt",
          numeric: true,
          cell: (item) => (
            <>
              {formatCount(item.turn)}{" "}
              {item.replayed === true && <Badge tone="info">Chạy lại</Badge>}
            </>
          ),
        },
        { header: "Bắt đầu", cell: (item) => formatTimestamp(item.start_time) },
        { header: "Tổng", numeric: true, cell: (item) => formatDuration(item.duration_ms) },
        { header: "Trạng thái", cell: (item) => <StatusBadge status={item.status} /> },
        {
          header: "STT",
          numeric: true,
          cell: (item) => formatDuration(item.stages.stt?.duration_ms),
        },
        {
          header: "Core",
          numeric: true,
          cell: (item) => formatDuration(item.stages.core?.duration_ms),
        },
        {
          header: "TTS",
          numeric: true,
          cell: (item) => formatDuration(item.stages.tts?.duration_ms),
        },
        { header: "Provider / model", cell: (item) => providerSummary(item) },
        {
          header: "",
          cell: (item) => (
            <TurnLink range={range} traceId={item.trace_id} callKey={item.call_key}>
              Xem stage →
            </TurnLink>
          ),
        },
      ]}
    />
  );
}

function providerSummary(item: TurnExecution): string {
  const stages = [item.stages.stt, item.stages.tts].filter((stage): stage is Stage =>
    Boolean(stage),
  );
  if (stages.length === 0) return "—";
  return stages
    .map(
      (stage) =>
        `${stage.component}: ${displayLabel(stage.provider)} / ${displayLabel(stage.model)}`,
    )
    .join(" · ");
}

/** Màu thanh theo thành phần; stage khác (vd. CLINIC) dùng màu trung tính. */
const BAR_COLOR: Readonly<Record<string, string | undefined>> = {
  TURN: styles.barTurn,
  STT: styles.barStt,
  CORE: styles.barCore,
  TTS: styles.barTts,
};

/**
 * Thời lượng tương đối của từng stage so với cả lượt. Không có mốc bắt đầu của stage nên đây
 * không phải timeline phân tán — chỉ so độ dài.
 */
export function TurnWaterfall({ data }: { data: TurnExecution }) {
  const stages = [data.stages.stt, data.stages.core, data.stages.tts, ...data.clinic].filter(
    (stage): stage is Stage => Boolean(stage),
  );
  const longest = Math.max(data.duration_ms, ...stages.map((stage) => stage.duration_ms), 1);
  const rows = [
    { component: "TURN", duration_ms: data.duration_ms, key: "turn" },
    ...stages.map((stage, index) => ({
      component: stage.component,
      duration_ms: stage.duration_ms,
      key: `${stage.component}-${String(index)}`,
    })),
  ];

  return (
    <div className={styles.view}>
      <div className={styles.waterfall}>
        {rows.map((row) => (
          <div key={row.key} className={styles.row}>
            <strong>{row.component}</strong>
            <div className={styles.track} aria-hidden>
              <span
                className={cx(styles.bar, BAR_COLOR[row.component])}
                style={{ width: `${String(Math.max(0.5, (row.duration_ms / longest) * 100))}%` }}
              />
            </div>
            <span className={styles.duration}>{formatDuration(row.duration_ms)}</span>
          </div>
        ))}
      </div>
      {stages.length === 0 ? (
        <StatePanel
          kind="empty"
          title="Không có dữ liệu stage"
          detail="Lượt này không ghi nhận telemetry theo stage."
        />
      ) : (
        <div className={styles.stages}>
          {stages.map((stage, index) => (
            <article key={`${stage.component}-${String(index)}`} className={styles.stage}>
              <header>
                <strong>{stage.component}</strong>
                <StatusBadge status={stage.status} />
              </header>
              <dl>
                <dt>Thời lượng</dt>
                <dd>{formatDuration(stage.duration_ms)}</dd>
                <dt>Thao tác</dt>
                <dd>
                  <code>{stage.operation}</code>
                </dd>
                <dt>Provider / model</dt>
                <dd>
                  {displayLabel(stage.provider)} / {displayLabel(stage.model)}
                </dd>
                <dt>Mã lỗi</dt>
                <dd>
                  <code>{stage.error_code ?? "—"}</code>
                </dd>
              </dl>
            </article>
          ))}
        </div>
      )}
    </div>
  );
}
