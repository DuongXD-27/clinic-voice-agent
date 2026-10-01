import { ArrowRight, X } from "lucide-react";
import { useState, type ReactNode } from "react";
import { Link } from "react-router";

import { Button } from "../../../components/ui/Button";
import { Card, CardBody, CardHeader } from "../../../components/ui/Card";
import { Select } from "../../../components/ui/Form";
import { observabilityApi } from "../api";
import { DataTable } from "../components/DataTable";
import { Pagination } from "../components/Pagination";
import { StatePanel } from "../components/StatePanel";
import {
  CallLink,
  ComponentErrorsTable,
  PercentileTable,
  ProviderTable,
  SlowTurnsTable,
  StatusBadge,
  TopErrorsTable,
  TurnLink,
} from "../components/tables";
import { TrendChart } from "../components/TrendChart";
import { formatCount, formatRate } from "../model/format";
import { obsPaths } from "../model/links";
import { SLOW_THRESHOLDS, type Component, type Metric } from "../model/overview";
import type { TimeWindow } from "../model/range";
import type { Overview } from "../model/types";
import { useQuery, type QueryState } from "../useQuery";
import styles from "./pages.module.css";

interface Props {
  metric: Metric;
  data: Overview;
  range: number;
  window: TimeWindow;
  windowKey: string;
  slowThreshold: number;
  onSlowThreshold: (value: number) => void;
  onClose: () => void;
}

const TITLES: Record<Metric, string> = {
  turn: "Latency cả lượt",
  stt: "Thời lượng observation STT",
  core: "Latency Core (engine hội thoại)",
  tts: "Latency TTS",
  error: "Lỗi",
  slow_turn: "Lượt chậm",
  empty_transcript: "Transcript rỗng",
};

/** Phần chi tiết của thẻ KPI đang chọn. Mỗi khối tự tải dữ liệu, lỗi khối nào hiện ở khối đó. */
export function MetricDetail(props: Props) {
  const { metric, onClose } = props;
  return (
    <section className={styles.detail} aria-labelledby="metric-detail-title">
      <header className={styles.detailHeader}>
        <h2 id="metric-detail-title">{TITLES[metric]}</h2>
        <Button variant="ghost" size="sm" icon={<X />} onClick={onClose}>
          Đóng
        </Button>
      </header>
      <DetailBody {...props} />
    </section>
  );
}

function DetailBody(props: Props) {
  const { metric, data, range } = props;
  switch (metric) {
    case "turn":
      return (
        <>
          <LatencySections data={data} component="TURN" />
          <SlowTurnsSection {...props} />
        </>
      );
    case "stt":
    case "tts": {
      const component = metric === "stt" ? "STT" : "TTS";
      return (
        <>
          <LatencySections data={data} component={component} />
          <Section title={`Provider / model ${component}`}>
            <ProviderTable
              rows={data.provider_model_breakdown.filter((row) => row.component === component)}
            />
          </Section>
          <ErrorsSection {...props} component={component} />
          <QualityLink range={range} component={component} />
        </>
      );
    }
    case "core":
      return (
        <>
          <LatencySections data={data} component="CORE" />
          <ErrorsSection {...props} component="CORE" />
        </>
      );
    case "error":
      return (
        <>
          <Section title="Tỷ lệ lỗi theo thành phần">
            <ComponentErrorsTable rows={data.component_errors} />
          </Section>
          <ErrorsSection {...props} component={null} />
          <Section title="Provider / model có lỗi">
            <ProviderTable
              rows={data.provider_model_breakdown.filter((row) => row.error_count > 0)}
            />
          </Section>
        </>
      );
    case "slow_turn":
      return <SlowTurnsSection {...props} />;
    case "empty_transcript":
      return <EmptyTranscriptSection {...props} />;
  }
}

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader title={title} action={action} />
      <CardBody>{children}</CardBody>
    </Card>
  );
}

function Loaded<T>({
  query,
  loading,
  children,
}: {
  query: QueryState<T>;
  loading: string;
  children: (data: T) => ReactNode;
}) {
  if (query.status === "loading") return <StatePanel kind="loading" title={loading} />;
  if (query.status === "error")
    return <StatePanel kind="error" title="Không tải được" detail={query.message} />;
  return children(query.data);
}

function LatencySections({ data, component }: { data: Overview; component: Component }) {
  return (
    <>
      <Section title={`${component} p95 theo giờ`}>
        <TrendChart hourly={data.hourly} components={[component]} />
      </Section>
      <Section title={`Phân vị ${component}`}>
        <PercentileTable data={data} components={[component]} />
      </Section>
    </>
  );
}

function ErrorsSection({ window, windowKey, component }: Props & { component: string | null }) {
  const errors = useQuery(`errors|${windowKey}`, (signal) =>
    observabilityApi.errors(window, signal),
  );
  return (
    <Section title={component ? `Mã lỗi ${component}` : "Mã lỗi thường gặp"}>
      <Loaded query={errors} loading="Đang tải mã lỗi…">
        {(result) => (
          <TopErrorsTable
            rows={
              component ? result.items.filter((item) => item.component === component) : result.items
            }
          />
        )}
      </Loaded>
    </Section>
  );
}

const SLOW_PAGE = 25;

function SlowTurnsSection({ range, window, windowKey, slowThreshold, onSlowThreshold }: Props) {
  const [offset, setOffset] = useState(0);
  // Đổi ngưỡng hoặc khoảng thời gian thì về trang đầu.
  const [scope, setScope] = useState(`${windowKey}|${String(slowThreshold)}`);
  const currentScope = `${windowKey}|${String(slowThreshold)}`;
  if (scope !== currentScope) {
    setScope(currentScope);
    setOffset(0);
  }

  const slow = useQuery(`slow|${currentScope}|${String(offset)}`, (signal) =>
    observabilityApi.slowTurns(window, slowThreshold, offset, SLOW_PAGE, signal),
  );

  const thresholdSelect = (
    <label className={styles.inline}>
      Ngưỡng
      <Select
        value={slowThreshold}
        onChange={(event) => {
          onSlowThreshold(Number(event.target.value));
        }}
      >
        {SLOW_THRESHOLDS.map((value) => (
          <option key={value} value={value}>
            {value / 1000} s
          </option>
        ))}
      </Select>
    </label>
  );

  return (
    <Section title="Lượt chậm" action={thresholdSelect}>
      <Loaded query={slow} loading="Đang tải lượt chậm…">
        {(result) => (
          <div className={styles.stack}>
            <SlowTurnsTable rows={result.items} range={range} />
            <Pagination
              offset={offset}
              count={result.items.length}
              hasNext={result.items.length === SLOW_PAGE}
              onChange={setOffset}
              pageSize={SLOW_PAGE}
            />
          </div>
        )}
      </Loaded>
    </Section>
  );
}

function EmptyTranscriptSection({ data, range, window, windowKey }: Props) {
  const quality = useQuery(`quality|${windowKey}|STT|call`, (signal) =>
    observabilityApi.quality(window, "STT", "call", signal),
  );
  return (
    <>
      <dl className={styles.summary}>
        <div>
          <dt>Bị ảnh hưởng</dt>
          <dd>{formatCount(data.stt_empty.empty_count)}</dd>
        </div>
        <div>
          <dt>Đủ điều kiện</dt>
          <dd>{formatCount(data.stt_empty.eligible_count)}</dd>
        </div>
        <div>
          <dt>Tỷ lệ</dt>
          <dd>{formatRate(data.stt_empty.rate)}</dd>
        </div>
      </dl>
      <Section title="Cuộc gọi / lượt bị ảnh hưởng">
        <Loaded query={quality} loading="Đang tải lượt bị ảnh hưởng…">
          {(result) => {
            const rows = result.candidates.filter(
              (item) => item.issue_code === "STT_EMPTY_TRANSCRIPT",
            );
            return rows.length === 0 ? (
              <StatePanel kind="empty" title="Không có lượt nào có transcript rỗng" />
            ) : (
              <DataTable
                label="Lượt có transcript rỗng"
                rows={rows}
                rowKey={(item) => item.trace_id}
                columns={[
                  {
                    header: "Cuộc gọi",
                    cell: (item) => <CallLink range={range} callKey={item.call_key} />,
                  },
                  { header: "Lượt", numeric: true, cell: (item) => formatCount(item.turn) },
                  { header: "Trạng thái", cell: (item) => <StatusBadge status={item.status} /> },
                  {
                    header: "",
                    cell: (item) => (
                      <TurnLink range={range} traceId={item.trace_id} callKey={item.call_key}>
                        Mở lượt →
                      </TurnLink>
                    ),
                  },
                ]}
              />
            );
          }}
        </Loaded>
      </Section>
      <QualityLink range={range} component="STT" />
    </>
  );
}

function QualityLink({ range, component }: { range: number; component: "STT" | "TTS" }) {
  return (
    <Link to={obsPaths.quality(range, { component })} className={styles.more}>
      Xem chất lượng {component} <ArrowRight aria-hidden />
    </Link>
  );
}
