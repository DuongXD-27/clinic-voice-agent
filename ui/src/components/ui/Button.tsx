import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cx } from "../../lib/cx";
import styles from "./Button.module.css";

export type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";

interface Props extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  icon?: ReactNode;
  /** Hiện vòng quay và khoá nút trong lúc chờ. */
  loading?: boolean;
}

export function Button({
  variant = "secondary",
  size = "md",
  icon,
  loading = false,
  disabled,
  className,
  children,
  type = "button",
  ...rest
}: Props) {
  return (
    <button
      type={type}
      className={cx(styles.button, styles[variant], styles[size], className)}
      disabled={disabled ?? loading}
      aria-busy={loading || undefined}
      {...rest}
    >
      {loading ? <span className={styles.spinner} aria-hidden /> : icon}
      {children}
    </button>
  );
}
