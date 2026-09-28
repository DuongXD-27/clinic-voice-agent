import { Database, RefreshCw, Server } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "../../components/ui/Button";
import { Card, CardBody, CardHeader } from "../../components/ui/Card";
import { StatusIndicator } from "../../components/ui/StatusIndicator";
import { describeProbe } from "../../features/system/describe";
import type { ServiceStatus } from "../../features/system/serviceStatusContext";
import styles from "./HomePage.module.css";

const TIME = new Intl.DateTimeFormat("vi-VN", { timeStyle: "medium" });

export function SystemStatusCard({ status }: { status: ServiceStatus }) {
  const checking = status.health.state === "checking" || status.readiness.state === "checking";
  return (
    <Card>
      <CardHeader
        title="Trạng thái hệ thống"
        description={
          status.checkedAt ? `Kiểm tra lúc ${TIME.format(status.checkedAt)}` : "Đang kiểm tra…"
        }
        action={
          <Button
            variant="ghost"
            size="sm"
            icon={<RefreshCw />}
            loading={checking}
            onClick={status.refresh}
            aria-label="Kiểm tra lại"
          />
        }
      />
      <CardBody className={styles.probes}>
        <ProbeRow
          icon={<Server />}
          name="API"
          path="/health"
          view={describeProbe(status.health, "Hoạt động")}
        />
        <ProbeRow
          icon={<Database />}
          name="Session store"
          path="/ready"
          view={describeProbe(status.readiness, "Sẵn sàng")}
        />
      </CardBody>
    </Card>
  );
}

interface RowProps {
  icon: ReactNode;
  name: string;
  path: string;
  view: ReturnType<typeof describeProbe>;
}

function ProbeRow({ icon, name, path, view }: RowProps) {
  return (
    <div className={styles.probe}>
      <span className={styles.probeIcon} aria-hidden>
        {icon}
      </span>
      <span className={styles.probeName}>
        {name}
        <code>{path}</code>
      </span>
      <StatusIndicator {...view} />
    </div>
  );
}
