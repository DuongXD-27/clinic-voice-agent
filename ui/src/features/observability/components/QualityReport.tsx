import { Button } from "../../../components/ui/Button";
import { Card, CardBody, CardHeader } from "../../../components/ui/Card";
import { cx } from "../../../lib/cx";
import { formatCount, formatRate } from "../model/format";
import { unitOf, type QualityView } from "../model/quality";
import type { Quality } from "../model/types";
import { DataTable } from "./DataTable";
import styles from "./QualityReport.module.css";
import { StatePanel } from "./StatePanel";
import { CallLink, StatusBadge, TurnLink } from "./tables";

type Issue = Quality["issues"][number];

interface Props {
  data: Quality;
  view: QualityView;
  issue: string | null;
  onIssue: (code: string | null) => void;
  range: number;
}

export function QualityReport({ data, view, issue, onIssue, range }: Props) {
  const unit = unitOf(data.aggregation === "turn" ? "turn" : "call");
  return (
    <div className={styles.report}>
      <Summary data={data} unit={unit} />
      <p className={styles.note}>
        Một {unit} có thể dính nhiều loại vấn đề, nên cộng tỷ lệ các loại có thể vượt tỷ lệ tổng.
      </p>
      {view !== "numbers" && (
        <Card>
          <CardHeader
            title="Tỷ lệ theo loại vấn đề"
            description="Bấm một loại để lọc bảng ví dụ bên dưới."
          />
          <CardBody className={styles.donuts}>
            {data.issues.map((item) => (
              <Donut
                key={item.code}
                issue={item}
                unit={unit}
                selected={item.code === issue}
                onSelect={onIssue}
              />
            ))}
          </CardBody>
        </Card>
      )}
      {view !== "charts" && (
        <Card>
          <CardHeader title="Breakdown theo loại vấn đề" />
          <CardBody>
            <DataTable
              label={`Vấn đề chất lượng ${data.component}`}
              rows={data.issues}
              rowKey={(item) => item.code}
              columns={[
                {
                  header: "Loại",
                  rowHeader: true,
                  cell: (item) => (
                    <>
                      {item.label} <code className={styles.issueCode}>{item.code}</code>
                    </>
                  ),
                },
                { header: "Mức", cell: (item) => <Severity value={item.severity} /> },
                {
                  header: "Số",
                  numeric: true,
                  cell: (item) =>
                    `${formatCount(item.affected_count)} / ${formatCount(item.eligible_count)}`,
                },
                { header: "Tỷ lệ", numeric: true, cell: (item) => formatRate(item.rate) },
                {
                  header: "",
                  cell: (item) => (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        onIssue(item.code);
                      }}
                    >
                      Xem ví dụ
                    </Button>
                  ),
                },
              ]}
            />
          </CardBody>
        </Card>
      )}
      <Candidates data={data} issue={issue} onIssue={onIssue} range={range} />
      <details className={styles.coverage}>
        <summary>Telemetry chưa instrument ({formatCount(data.coverage.length)})</summary>
        <ul>
          {data.coverage.map((item) => (
            <li key={item.metric}>
              <strong>{item.metric}</strong>
              <span>{item.detail}</span>
              <code>{item.instrumentation_status.replaceAll("_", " ")}</code>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

function Summary({ data, unit }: { data: Quality; unit: string }) {
  const width = Math.max(0, Math.min(1, data.affected_rate ?? 0)) * 100;
  return (
    <Card>
      <CardBody className={styles.summary}>
        <div className={styles.rate}>
          <strong>{formatRate(data.affected_rate)}</strong>
          <span>
            {unit} có ít nhất một vấn đề {data.component}
          </span>
        </div>
        <div className={styles.counts}>
          <div
            className={styles.bar}
            role="img"
            aria-label={`${formatCount(data.affected_count)} bị ảnh hưởng, ${formatCount(data.clean_count)} sạch`}
          >
            <span style={{ width: `${String(width)}%` }} />
          </div>
          <dl>
            <div>
              <dt>Bị ảnh hưởng</dt>
              <dd>{formatCount(data.affected_count)}</dd>
            </div>
            <div>
              <dt>Sạch</dt>
              <dd>{formatCount(data.clean_count)}</dd>
            </div>
            <div>
              <dt>Đủ điều kiện</dt>
              <dd>{formatCount(data.eligible_count)}</dd>
            </div>
          </dl>
        </div>
        {data.eligible_count === 0 ? (
          <StatePanel
            kind="empty"
            title="Chưa có dữ liệu"
            detail={`Không có ${unit} ${data.component} nào trong khoảng này.`}
          />
        ) : (
          data.affected_count === 0 && (
            <p className={styles.clean} role="status">
              Không ghi nhận vấn đề chất lượng {data.component} trong khoảng thời gian này.
            </p>
          )
        )}
      </CardBody>
    </Card>
  );
}

function Donut({
  issue,
  unit,
  selected,
  onSelect,
}: {
  issue: Issue;
  unit: string;
  selected: boolean;
  onSelect: (code: string | null) => void;
}) {
  const percent = Math.max(0, Math.min(1, issue.rate ?? 0)) * 100;
  return (
    <button
      type="button"
      className={cx(styles.donut, selected && styles.selected)}
      aria-pressed={selected}
      aria-label={`${issue.label}: ${formatRate(issue.rate)}, ${formatCount(issue.affected_count)} trên ${formatCount(issue.eligible_count)} ${unit}`}
      onClick={() => {
        onSelect(selected ? null : issue.code);
      }}
    >
      <svg viewBox="0 0 120 120" aria-hidden>
        <circle className={styles.track} cx="60" cy="60" r="48" />
        <circle
          className={styles.value}
          cx="60"
          cy="60"
          r="48"
          pathLength={100}
          strokeDasharray={`${String(percent)} ${String(100 - percent)}`}
          transform="rotate(-90 60 60)"
        />
        <text x="60" y="66" textAnchor="middle">
          {formatRate(issue.rate)}
        </text>
      </svg>
      <strong>{issue.label}</strong>
      <span>
        {formatCount(issue.affected_count)} / {formatCount(issue.eligible_count)} {unit}
      </span>
    </button>
  );
}

function Severity({ value }: { value: string }) {
  return (
    <span className={cx(styles.severity, value === "Lỗi" && styles.severityError)}>{value}</span>
  );
}

function Candidates({
  data,
  issue,
  onIssue,
  range,
}: {
  data: Quality;
  issue: string | null;
  onIssue: (code: string | null) => void;
  range: number;
}) {
  const rows = issue
    ? data.candidates.filter((item) => item.issue_code === issue)
    : data.candidates;
  const label = data.issues.find((item) => item.code === issue)?.label;
  return (
    <Card>
      <CardHeader
        title={label ? `Ví dụ: ${label}` : "Ví dụ để kiểm tra"}
        description="Chỉ hiện mã cuộc gọi ẩn danh và trạng thái an toàn, không có nội dung hội thoại."
        action={
          issue && (
            <Button
              size="sm"
              onClick={() => {
                onIssue(null);
              }}
            >
              Bỏ lọc
            </Button>
          )
        }
      />
      <CardBody>
        {rows.length === 0 ? (
          <StatePanel
            kind="empty"
            title="Không có ví dụ"
            detail="Không có lượt bị ảnh hưởng cho bộ lọc hiện tại."
          />
        ) : (
          <DataTable
            label="Lượt bị ảnh hưởng"
            rows={rows}
            rowKey={(item, index) => `${item.trace_id}-${item.issue_code}-${String(index)}`}
            columns={[
              {
                header: "Cuộc gọi",
                cell: (item) => <CallLink range={range} callKey={item.call_key} />,
              },
              { header: "Lượt", numeric: true, cell: (item) => formatCount(item.turn) },
              {
                header: "Vấn đề",
                cell: (item) => (
                  <>
                    {item.issue_label} <code className={styles.issueCode}>{item.safe_value}</code>
                  </>
                ),
              },
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
        )}
      </CardBody>
    </Card>
  );
}
