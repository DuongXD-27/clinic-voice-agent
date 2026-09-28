import { ArrowRight } from "lucide-react";
import { Link } from "react-router";

import type { Tool } from "../../app/navigation";
import styles from "./HomePage.module.css";

export function ToolCard({ tool }: { tool: Tool }) {
  const Icon = tool.icon;
  return (
    <Link to={tool.to} className={styles.tool}>
      <span className={styles.toolIcon} aria-hidden>
        <Icon />
      </span>
      <span className={styles.toolText}>
        <span className={styles.toolTitle}>{tool.label}</span>
        <span className={styles.toolDescription}>{tool.description}</span>
      </span>
      <ArrowRight className={styles.toolArrow} aria-hidden />
    </Link>
  );
}
