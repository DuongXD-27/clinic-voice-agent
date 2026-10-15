import { HeartPulse, type LucideIcon } from "lucide-react";
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
  sections: readonly NavSection[];
  status: { tone: StatusTone; label: string; pulse: boolean };
}

export function Sidebar({ sections, status }: Props) {
  return (
    <aside className={styles.sidebar}>
      <NavLink to="/" className={styles.brand}>
        <span className={styles.logo} aria-hidden>
          <HeartPulse />
        </span>
        <span>
          <strong>Callbot</strong>
          <small>Console nội bộ</small>
        </span>
      </NavLink>

      <nav className={styles.nav} aria-label="Điều hướng chính">
        {sections.map((section, index) => (
          <div key={section.title ?? index} className={styles.section}>
            {section.title && <p className={styles.sectionTitle}>{section.title}</p>}
            <ul>
              {section.items.map((item) => (
                <li key={item.label}>
                  <NavEntry item={item} />
                </li>
              ))}
            </ul>
          </div>
        ))}
      </nav>

      <footer className={styles.footer} role="status">
        <StatusIndicator {...status} />
      </footer>
    </aside>
  );
}

function NavEntry({ item }: { item: NavItem }) {
  const Icon = item.icon;
  const content = (
    <>
      <Icon className={styles.icon} aria-hidden />
      <span className={styles.label}>{item.label}</span>
      {item.kind === "link" && item.badge && <span className={styles.badge}>{item.badge}</span>}
    </>
  );
  if (item.kind === "route") {
    return (
      <NavLink
        to={item.to}
        // Trang chủ chỉ sáng khi đúng "/"; mục khác sáng cả ở trang con (vd. /observability/quality).
        end={item.to === "/"}
        className={({ isActive }) => cx(styles.link, isActive && styles.active)}
      >
        {content}
      </NavLink>
    );
  }
  return (
    <a href={item.href} className={styles.link}>
      {content}
    </a>
  );
}
