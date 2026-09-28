import type { ComponentProps, ReactNode } from "react";

import { cx } from "../../lib/cx";
import styles from "./Form.module.css";

interface FieldProps {
  label: string;
  /** id của ô nhập; bỏ trống khi con là nhóm (radiogroup tự có aria-label). */
  htmlFor?: string;
  hint?: ReactNode;
  error?: string | null;
  /** Chiếm cả hàng trong lưới 2 cột. */
  wide?: boolean;
  children: ReactNode;
}

export function Field({ label, htmlFor, hint, error, wide = false, children }: FieldProps) {
  return (
    <div className={cx(styles.field, wide && styles.wide)}>
      {htmlFor ? (
        <label htmlFor={htmlFor} className={styles.label}>
          {label}
        </label>
      ) : (
        <span className={styles.label} aria-hidden>
          {label}
        </span>
      )}
      {children}
      {error ? (
        <p className={styles.error} role="alert">
          {error}
        </p>
      ) : (
        hint && <p className={styles.hint}>{hint}</p>
      )}
    </div>
  );
}

export function FieldGrid({ children }: { children: ReactNode }) {
  return <div className={styles.grid}>{children}</div>;
}

interface Invalid {
  invalid?: boolean;
}

export function Input({ invalid, className, ...rest }: ComponentProps<"input"> & Invalid) {
  return (
    <input
      className={cx(styles.control, invalid && styles.invalid, className)}
      aria-invalid={invalid}
      {...rest}
    />
  );
}

export function Select({ invalid, className, ...rest }: ComponentProps<"select"> & Invalid) {
  return (
    <select
      className={cx(styles.control, styles.select, invalid && styles.invalid, className)}
      aria-invalid={invalid}
      {...rest}
    />
  );
}

export function Textarea({ invalid, className, ...rest }: ComponentProps<"textarea"> & Invalid) {
  return (
    <textarea
      className={cx(styles.control, styles.textarea, invalid && styles.invalid, className)}
      aria-invalid={invalid}
      {...rest}
    />
  );
}
