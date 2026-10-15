import { LogOut, PanelLeftClose, PanelLeftOpen, X, type LucideIcon } from "lucide-react";
import { useEffect, useRef } from "react";
import { NavLink } from "react-router";

import { cx } from "../../lib/cx";
import { StatusIndicator, type StatusTone } from "../ui/StatusIndicator";
import styles from "./Sidebar.module.css";

/** `route`: trang trong app này; `link`: trang ngoài app (bản cũ, Swagger). */
export type NavItem =
  | { kind: "route"; label: string; icon: LucideIcon; to: string }
  | { kind: "link"; label: string; icon: LucideIcon; href: string; badge?: string };

export interface NavSection {
  title?: string;
  items: readonly NavItem[];
}

interface Props {
  id: string;
  sections: readonly NavSection[];
  status: { tone: StatusTone; label: string; pulse: boolean };
  onLogout: () => void;
  /** Màn rộng: thu gọn thành dải icon. */
  collapsed: boolean;
  onToggleCollapsed: () => void;
  /** Màn hẹp: thanh bên là ngăn kéo, mở bằng nút menu ở thanh trên. */
  open: boolean;
  onClose: () => void;
}

export function Sidebar({
  id,
  sections,
  status,
  onLogout,
  collapsed,
  onToggleCollapsed,
  open,
  onClose,
}: Props) {
  // Mở ngăn kéo: đưa focus vào trong để bàn phím / trình đọc màn hình đi tiếp từ đây.
  const closeRef = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (open) closeRef.current?.focus();
  }, [open]);

  return (
    <aside
      id={id}
      className={cx(styles.sidebar, collapsed && styles.collapsed, open && styles.open)}
      aria-label="Thanh bên"
    >
      <div className={styles.head}>
        <NavLink to="/" className={styles.brand} onClick={onClose}>
          <strong>Clinicalbot</strong>
          <small>Console nội bộ</small>
        </NavLink>
        <button
          type="button"
          className={cx(styles.iconButton, styles.collapseToggle)}
          aria-label={collapsed ? "Mở rộng thanh bên" : "Thu gọn thanh bên"}
          title={collapsed ? "Mở rộng thanh bên" : "Thu gọn thanh bên"}
          aria-expanded={!collapsed}
          aria-controls={id}
          onClick={onToggleCollapsed}
        >
          {collapsed ? <PanelLeftOpen aria-hidden /> : <PanelLeftClose aria-hidden />}
        </button>
        <button
          ref={closeRef}
          type="button"
          className={cx(styles.iconButton, styles.close)}
          aria-label="Đóng menu"
          onClick={onClose}
        >
          <X aria-hidden />
        </button>
      </div>

      <nav className={styles.nav} aria-label="Điều hướng chính">
        {sections.map((section, index) => (
          <div key={section.title ?? index} className={styles.section}>
            {section.title && <p className={styles.sectionTitle}>{section.title}</p>}
            <ul>
              {section.items.map((item) => (
                <li key={item.label}>
                  <NavEntry item={item} collapsed={collapsed} onNavigate={onClose} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <footer className={styles.footer}>
        <div role="status" className={styles.status} title={status.label}>
          <StatusIndicator {...status} />
        </div>
        <button
          type="button"
          className={styles.logout}
          title={collapsed ? "Đăng xuất" : undefined}
          onClick={onLogout}
        >
          <LogOut aria-hidden />
          <span className={styles.label}>Đăng xuất</span>
        </button>
      </footer>
    </aside>
  );
}

function NavEntry({
  item,
  collapsed,
  onNavigate,
}: {
  item: NavItem;
  collapsed: boolean;
  onNavigate: () => void;
}) {
  const Icon = item.icon;
  const content = (
    <>
      <Icon className={styles.icon} aria-hidden />
      <span className={styles.label}>{item.label}</span>
      {item.kind === "link" && item.badge && <span className={styles.badge}>{item.badge}</span>}
    </>
  );
  // Thu gọn chỉ còn icon: tên hiện khi rê chuột.
  const title = collapsed ? item.label : undefined;
  if (item.kind === "route") {
    return (
      <NavLink
        to={item.to}
        // Trang chủ chỉ sáng khi đúng "/"; mục khác sáng cả ở trang con (vd. /observability/quality).
        end={item.to === "/"}
        className={({ isActive }) => cx(styles.link, isActive && styles.active)}
        title={title}
        onClick={onNavigate}
      >
        {content}
      </NavLink>
    );
  }
  return (
    <a href={item.href} className={styles.link} title={title}>
      {content}
    </a>
  );
}
