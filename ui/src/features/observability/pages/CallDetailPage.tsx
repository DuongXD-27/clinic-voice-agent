import { ArrowLeft } from "lucide-react";
import { Link, useParams, useSearchParams } from "react-router";

import { Card, CardBody, CardHeader } from "../../../components/ui/Card";
import { observabilityApi } from "../api";
import { CallExecutions } from "../components/ExecutionViews";
import { Pagination } from "../components/Pagination";
import { StatePanel } from "../components/StatePanel";
import { formatCount } from "../model/format";
import { obsPaths } from "../model/links";
import { useQuery } from "../useQuery";
import { useObservability } from "./context";
import styles from "./pages.module.css";

const PAGE_SIZE = 50;

export function CallDetailPage() {
  const { callKey = "" } = useParams();
  const { range, window, windowKey } = useObservability();
  const [params, setParams] = useSearchParams();
  const offset = Math.max(0, Number(params.get("offset")) || 0);

  const call = useQuery(`call|${callKey}|${windowKey}|${String(offset)}`, (signal) =>
    observabilityApi.call(callKey, window, offset, PAGE_SIZE, signal),
  );

  return (
    <div className={styles.page}>
      <Link to={obsPaths.overview(range)} className={styles.back}>
        <ArrowLeft aria-hidden /> Tổng quan
      </Link>
      <Card>
        <CardHeader
          title="Chi tiết cuộc gọi"
          description={
            <>
              Mã ẩn danh <code>{callKey}</code>
              {call.status === "ready" &&
                ` · ${formatCount(call.data.total_executions)} lượt đã chạy`}
            </>
          }
        />
        <CardBody className={styles.stack}>
          {call.status === "loading" && <StatePanel kind="loading" title="Đang tải các lượt…" />}
          {call.status === "error" && (
            <StatePanel kind="error" title="Không tải được cuộc gọi" detail={call.message} />
          )}
          {call.status === "ready" && (
            <>
              <CallExecutions data={call.data} range={range} />
              <Pagination
                offset={offset}
                count={call.data.executions.length}
                total={call.data.total_executions}
                hasNext={offset + call.data.executions.length < call.data.total_executions}
                pageSize={PAGE_SIZE}
                onChange={(next) => {
                  setParams((current) => {
                    const updated = new URLSearchParams(current);
                    updated.set("offset", String(next));
                    return updated;
                  });
                }}
              />
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}
