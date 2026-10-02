import type { Overview } from "../model/types";
import { CHART_BOX, chartMax, gridLines, seriesGeometry } from "../model/chart";
import { formatDuration, formatTimestamp } from "../model/format";
import type { Component } from "../model/overview";
import { DataTable } from "./DataTable";
import styles from "./TrendChart.module.css";
import { StatePanel } from "./StatePanel";

type Bucket = Overview["hourly"][number];

const SERIES: Record<
  Component,
  { label: string; value: (bucket: Bucket) => number | null; color: string }
> = {
  TURN: {
    label: "Lượt",
    value: (bucket) => bucket.turn_p95_ms,
    color: "var(--chart-turn)",
  },
  STT: {
    label: "STT observation",
    value: (bucket) => bucket.stt_p95_ms,
    color: "var(--chart-stt)",
  },
  CORE: {
    label: "Core",
    value: (bucket) => bucket.core_p95_ms,
    color: "var(--chart-core)",
  },
  TTS: { label: "TTS", value: (bucket) => bucket.tts_p95_ms, color: "var(--chart-tts)" },
};

interface Props {
  hourly: readonly Bucket[];
  components: readonly Component[];
}

/** p95 theo giờ; giờ không có mẫu để trống. Có bảng số liệu tương đương cho trình đọc màn hình. */
export function TrendChart({ hourly, components }: Props) {
  if (hourly.length === 0) {
    return (
      <StatePanel
        kind="empty"
        title="Chưa có dữ liệu theo giờ"
        detail="Không có lượt nào hoàn tất trong khoảng thời gian này."
      />
    );
  }
  const series = components.map((component) => ({
    component,
    ...SERIES[component],
    values: hourly.map(SERIES[component].value),
  }));
  const max = chartMax(series.map((item) => item.values));
  if (series.every((item) => item.values.every((value) => value === null))) {
    return (
      <StatePanel
        kind="empty"
        title="Chưa có số liệu latency"
        detail="Có lượt trong khoảng này nhưng chưa có mẫu cho thành phần đã chọn."
      />
    );
  }

  return (
    <div className={styles.wrap}>
      <div className={styles.legend}>
        {series.map((item) => (
          <span key={item.component}>
            <i style={{ background: item.color }} aria-hidden />
            {item.label} p95
          </span>
        ))}
      </div>
      <svg
        className={styles.chart}
        viewBox={`0 0 ${String(CHART_BOX.width)} ${String(CHART_BOX.height)}`}
        role="img"
        aria-label="Biểu đồ p95 latency theo giờ; giờ không có mẫu để trống"
      >
        {gridLines(max).map((line) => (
          <g key={line.value}>
            <line
              className={styles.grid}
              x1={CHART_BOX.left}
              x2={CHART_BOX.width - 16}
              y1={line.y}
              y2={line.y}
            />
            <text className={styles.axis} x={CHART_BOX.left - 8} y={line.y + 4} textAnchor="end">
              {formatDuration(line.value)}
            </text>
          </g>
        ))}
        {series.map((item) => {
          const geometry = seriesGeometry(item.values, max);
          return (
            <g key={item.component} stroke={item.color} fill={item.color}>
              {geometry.segments.map(([from, to]) => (
                <line
                  key={`${String(from.index)}-${String(to.index)}`}
                  className={styles.line}
                  x1={from.x}
                  y1={from.y}
                  x2={to.x}
                  y2={to.y}
                />
              ))}
              {geometry.points.map((point) => (
                <circle key={point.index} cx={point.x} cy={point.y} r={3.5}>
                  <title>
                    {`${item.label} ${formatDuration(point.value)} · ${formatTimestamp(hourly[point.index]?.start_time)}`}
                  </title>
                </circle>
              ))}
            </g>
          );
        })}
      </svg>
      <details className={styles.values}>
        <summary>Xem số liệu theo giờ</summary>
        <DataTable
          label="Số liệu p95 theo giờ"
          rows={hourly}
          rowKey={(bucket) => bucket.start_time}
          columns={[
            {
              header: "Giờ",
              cell: (bucket) => formatTimestamp(bucket.start_time),
              rowHeader: true,
            },
            ...series.map((item) => ({
              header: `${item.label} p95`,
              numeric: true,
              cell: (bucket: Bucket) => formatDuration(item.value(bucket)),
            })),
          ]}
        />
      </details>
    </div>
  );
}
