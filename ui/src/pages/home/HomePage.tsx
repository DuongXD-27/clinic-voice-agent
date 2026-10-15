import { TOOLS } from "../../app/navigation";
import { PageHeader } from "../../components/layout/PageHeader";
import { useServiceStatus } from "../../features/system/serviceStatusContext";
import styles from "./HomePage.module.css";
import { SystemStatusCard } from "./SystemStatusCard";
import { ToolCard } from "./ToolCard";

export function HomePage() {
  const status = useServiceStatus();
  return (
    <>
      <PageHeader
        eyebrow="Clinicalbot"
        title="Tổng quan"
        description="Công cụ nội bộ để gọi thử, kiểm tra và theo dõi callbot đặt, xác nhận, huỷ và đổi lịch khám."
      />
      <div className={styles.grid}>
        <section aria-labelledby="tools-heading" className={styles.tools}>
          <h2 id="tools-heading" className={styles.sectionTitle}>
            Công cụ
          </h2>
          {TOOLS.map((tool) => (
            <ToolCard key={tool.label} tool={tool} />
          ))}
        </section>
        <aside>
          <SystemStatusCard status={status} />
        </aside>
      </div>
    </>
  );
}
