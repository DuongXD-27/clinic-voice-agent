import { Menu } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, Outlet } from "react-router";

import { Sidebar } from "../components/layout/Sidebar";
import { describeOverall } from "../features/system/describe";
import { ServiceStatusProvider } from "../features/system/ServiceStatusProvider";
import { useServiceStatus } from "../features/system/serviceStatusContext";
import { logout } from "../lib/auth";
import styles from "./AppLayout.module.css";
import { NAV_SECTIONS } from "./navigation";

const SIDEBAR_ID = "app-sidebar";
/** Thu gọn thanh bên: tiện ích riêng của người xem, nhớ trong trình duyệt này. */
const COLLAPSED_KEY = "callbotSidebarCollapsed";

function readCollapsed(): boolean {
  try {
    return window.localStorage.getItem(COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}

function saveCollapsed(collapsed: boolean) {
  try {
    window.localStorage.setItem(COLLAPSED_KEY, collapsed ? "1" : "0");
  } catch {
    // Không lưu được thì lần sau mở rộng như mặc định.
  }
}

export function AppLayout() {
  return (
    <ServiceStatusProvider>
      <Shell />
    </ServiceStatusProvider>
  );
}

function Shell() {
  const status = useServiceStatus();
  const [collapsed, setCollapsed] = useState(readCollapsed);
  const [menuOpen, setMenuOpen] = useState(false);
  const closeMenu = () => {
    setMenuOpen(false);
  };

  // Ngăn kéo đang mở (màn hẹp): Esc để đóng.
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setMenuOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("keydown", onKey);
    };
  }, [menuOpen]);

  return (
    <div className={styles.shell}>
      <header className={styles.topbar}>
        <button
          type="button"
          className={styles.menuButton}
          aria-label="Mở menu"
          aria-expanded={menuOpen}
          aria-controls={SIDEBAR_ID}
          onClick={() => {
            setMenuOpen(true);
          }}
        >
          <Menu aria-hidden />
        </button>
        <Link to="/" className={styles.topBrand}>
          Clinicalbot
        </Link>
      </header>
      {menuOpen && <div className={styles.backdrop} aria-hidden onClick={closeMenu} />}
      <Sidebar
        id={SIDEBAR_ID}
        sections={NAV_SECTIONS}
        status={describeOverall(status)}
        onLogout={logout}
        collapsed={collapsed}
        onToggleCollapsed={() => {
          saveCollapsed(!collapsed);
          setCollapsed(!collapsed);
        }}
        open={menuOpen}
        onClose={closeMenu}
      />
      <main className={styles.main}>
        <div className={styles.content}>
          <Outlet />
        </div>
      </main>
    </div>
  );
}
