import { Outlet } from "react-router";

import { Sidebar } from "../components/layout/Sidebar";
import { describeOverall } from "../features/system/describe";
import { ServiceStatusProvider } from "../features/system/ServiceStatusProvider";
import { useServiceStatus } from "../features/system/serviceStatusContext";
import styles from "./AppLayout.module.css";
import { NAV_SECTIONS } from "./navigation";

export function AppLayout() {
  return (
    <ServiceStatusProvider>
      <Shell />
    </ServiceStatusProvider>
  );
}

function Shell() {
  const status = useServiceStatus();
  return (
    <div className={styles.shell}>
      <Sidebar sections={NAV_SECTIONS} status={describeOverall(status)} />
      <main className={styles.main}>
        <div className={styles.content}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
