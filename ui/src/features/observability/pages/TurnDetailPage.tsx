import { ArrowLeft } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router";

import { Badge } from "../../../components/ui/Badge";
import { Card, CardBody, CardHeader } from "../../../components/ui/Card";
import { observabilityApi } from "../api";
import { TurnWaterfall } from "../components/ExecutionViews";
import { StatePanel } from "../components/StatePanel";
import { StatusBadge } from "../components/tables";
import { formatCount, formatDuration, formatTimestamp } from "../model/format";
import { obsPaths } from "../model/links";
import { useQuery } from "../useQuery";
import { useObservability } from "./context";
import styles from "./pages.module.css";

export function TurnDetailPage() {
  const { traceId = "" } = useParams();
  const [params] = useSearchParams();
  const callKey = params.get("call");
  const { range, window, windowKey } = useObservability();

  const turn = useQuery(`turn|${traceId}|${windowKey}`, (signal) =>
    observabilityApi.turn(traceId, window, signal),
  );

  const back = callKey ?? (turn.status === "ready" ? turn.data.call_key : null);

  return (
    <div className={styles.page}>
      <Link
        to={back ? obsPaths.call(range, back) : obsPaths.overview(range)}
        className={styles.back}
      >
        <ArrowLeft aria-hidden /> {back ? "Cuộc gọi" : "Tổng quan"}
      </Link>
      {turn.status === "loading" && <StatePanel kind="loading" title="Đang tải lượt…" />}
      {turn.status === "error" && (
        <StatePanel kind="error" title="Không tải được lượt" detail={turn.message} />
      )}
      {turn.status === "ready" && (
        <>
          <dl className={styles.summary}>
            <div>
              <dt>Lượt</dt>
              <dd>
                {formatCount(turn.data.turn)}{" "}
                {turn.data.replayed === true && <Badge tone="info">Chạy lại</Badge>}
              </dd>
            </div>
            <div>
              <dt>Tổng thời gian</dt>
              <dd>{formatDuration(turn.data.duration_ms)}</dd>
            </div>
            <div>
              <dt>Trạng thái</dt>
              <dd>
                <StatusBadge status={turn.data.status} />
              </dd>
            </div>
            <div>
              <dt>Bắt đầu</dt>
              <dd>{formatTimestamp(turn.data.start_time)}</dd>
            </div>
            <div>
              <dt>Mã lỗi</dt>
              <dd>
                <code>{turn.data.error_codes.join(", ") || "—"}</code>
              </dd>
            </div>
          </dl>
          <Card>
            <CardHeader
              title="Các stage của lượt"
              description={
                <>
                  Trace <code>{turn.data.trace_id}</code> · độ dài tương đối, không phải timeline
                </>
              }
            />
            <CardBody>
              <TurnWaterfall data={turn.data} />
            </CardBody>
          </Card>
        </>
      )}
    </div>
  );
}
