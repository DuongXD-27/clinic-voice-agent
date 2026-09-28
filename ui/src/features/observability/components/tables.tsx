import { Link } from "react-router";

import { Badge } from "../../../components/ui/Badge";
import type { ErrorList, Overview, SlowTurnList } from "../model/types";
import {
  displayLabel,
  formatCount,
  formatDuration,
  formatRate,
  formatTimestamp,
} from "../model/format";
import { obsPaths } from "../model/links";
import { latencyOf, type Component } from "../model/overview";
import { DataTable } from "./DataTable";
import { StatePanel } from "./StatePanel";
import styles from "./tables.module.css";

export function StatusBadge({ status }: { status: string }) {
  const normalized = status.toUpperCase();
  const tone = normalized === "OK" ? "success" : normalized === "ERROR" ? "danger" : "neutral";
  return <Badge tone={tone}>{normalized}</Badge>;
}

export function CallLink({ range, callKey }: { range: number; callKey: string }) {
  return (
    <Link to={obsPaths.call(range, callKey)} className={styles.code} title={callKey}>
      {callKey}
    </Link>
  );
}

export function TurnLink({
  range,
  traceId,
  callKey,
  children,
}: {
  range: number;
  traceId: string;
  callKey: string;
  children: string;
}) {
  return (
    <Link to={obsPaths.turn(range, traceId, callKey)} className={styles.link}>
      {children}
    </Link>
  );
}

export function PercentileTable({
  data,
  components,
}: {
  data: Overview;
  components: readonly Component[];
}) {
  return (
    <DataTable
      label="Phân vị latency"
      rows={components}
      rowKey={(component) => component}
      columns={[
        { header: "Thành phần", cell: (component) => component, rowHeader: true },
        {
          header: "Mẫu",
          numeric: true,
          cell: (component) => formatCount(latencyOf(data, component).count),
        },
        {
          header: "p50",
          numeric: true,
          cell: (component) => formatDuration(latencyOf(data, component).p50_ms),
        },
        {
          header: "p95",
          numeric: true,
          cell: (component) => formatDuration(latencyOf(data, component).p95_ms),
        },
        {
          header: "p99",
          numeric: true,
          cell: (component) => formatDuration(latencyOf(data, component).p99_ms),
        },
      ]}
    />
  );
}

type ProviderRow = Overview["provider_model_breakdown"][number];

export function ProviderTable({ rows }: { rows: readonly ProviderRow[] }) {
  if (rows.length === 0) {
    return <StatePanel kind="empty" title="Chưa có dữ liệu provider / model" />;
  }
  return (
    <DataTable
      label="Hiệu năng theo provider và model"
      rows={rows}
      rowKey={(row) => `${row.component}-${row.provider}-${row.model}`}
      columns={[
        { header: "Thành phần", cell: (row) => row.component, rowHeader: true },
        { header: "Provider", cell: (row) => displayLabel(row.provider) },
        { header: "Model", cell: (row) => displayLabel(row.model) },
        { header: "Mẫu", numeric: true, cell: (row) => formatCount(row.count) },
        { header: "p50", numeric: true, cell: (row) => formatDuration(row.latency.p50_ms) },
        { header: "p95", numeric: true, cell: (row) => formatDuration(row.latency.p95_ms) },
        { header: "Lỗi", numeric: true, cell: (row) => formatCount(row.error_count) },
        { header: "Tỷ lệ lỗi", numeric: true, cell: (row) => formatRate(row.error_rate) },
      ]}
    />
  );
}

type ComponentErrorRow = Overview["component_errors"][number];

export function ComponentErrorsTable({ rows }: { rows: readonly ComponentErrorRow[] }) {
  if (rows.length === 0) return <StatePanel kind="empty" title="Chưa có mẫu theo thành phần" />;
  return (
    <DataTable
      label="Tỷ lệ lỗi theo thành phần"
      rows={rows}
      rowKey={(row) => row.component}
      columns={[
        { header: "Thành phần", cell: (row) => row.component, rowHeader: true },
        {
          header: "Lỗi / mẫu",
          numeric: true,
          cell: (row) => `${formatCount(row.error_count)} / ${formatCount(row.count)}`,
        },
        { header: "Tỷ lệ lỗi", numeric: true, cell: (row) => formatRate(row.error_rate) },
      ]}
    />
  );
}

type ErrorRow = ErrorList["items"][number];

export function TopErrorsTable({ rows }: { rows: readonly ErrorRow[] }) {
  if (rows.length === 0) {
    return (
      <StatePanel
        kind="empty"
        title="Không có lỗi"
        detail="Không ghi nhận mã lỗi nào trong khoảng này."
      />
    );
  }
  return (
    <DataTable
      label="Mã lỗi thường gặp"
      rows={rows}
      rowKey={(row, index) => `${row.component}-${row.error_code ?? "none"}-${String(index)}`}
      columns={[
        { header: "Thành phần", cell: (row) => row.component, rowHeader: true },
        { header: "Provider", cell: (row) => displayLabel(row.provider) },
        { header: "Model", cell: (row) => displayLabel(row.model) },
        { header: "Mã lỗi", cell: (row) => <code>{displayLabel(row.error_code)}</code> },
        { header: "Số lần", numeric: true, cell: (row) => formatCount(row.count) },
      ]}
    />
  );
}

type SlowRow = SlowTurnList["items"][number];

export function SlowTurnsTable({ rows, range }: { rows: readonly SlowRow[]; range: number }) {
  if (rows.length === 0) {
    return (
      <StatePanel
        kind="empty"
        title="Không có lượt chậm"
        detail="Không lượt nào vượt ngưỡng đã chọn."
      />
    );
  }
  return (
    <DataTable
      label="Lượt vượt ngưỡng thời gian"
      rows={rows}
      rowKey={(row) => row.trace_id}
      columns={[
        { header: "Thời điểm", cell: (row) => formatTimestamp(row.start_time) },
        { header: "Cuộc gọi", cell: (row) => <CallLink range={range} callKey={row.call_key} /> },
        { header: "Lượt", numeric: true, cell: (row) => formatCount(row.turn) },
        { header: "Tổng", numeric: true, cell: (row) => formatDuration(row.duration_ms) },
        { header: "STT", numeric: true, cell: (row) => formatDuration(row.stt_ms) },
        { header: "Core", numeric: true, cell: (row) => formatDuration(row.core_ms) },
        { header: "TTS", numeric: true, cell: (row) => formatDuration(row.tts_ms) },
        { header: "Trạng thái", cell: (row) => <StatusBadge status={row.status} /> },
        { header: "Mã lỗi", cell: (row) => <code>{row.error_codes.join(", ") || "—"}</code> },
        {
          header: "",
          cell: (row) => (
            <TurnLink range={range} traceId={row.trace_id} callKey={row.call_key}>
              Chi tiết →
            </TurnLink>
          ),
        },
      ]}
    />
  );
}
