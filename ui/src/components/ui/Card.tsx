import type { HTMLAttributes, ReactNode } from "react";

import { cx } from "../../lib/cx";
import styles from "./Card.module.css";

export function Card({ className, ...rest }: HTMLAttributes<HTMLElement>) {
  return <section className={cx(styles.card, className)} {...rest} />;
}

interface HeaderProps {
  title: ReactNode;
  description?: ReactNode;
  action?: ReactNode;
}

export function CardHeader({ title, description, action }: HeaderProps) {
  return (
    <header className={styles.header}>
      <div>
        <h2 className={styles.title}>{title}</h2>
        {description && <p className={styles.description}>{description}</p>}
      </div>
      {action}
    </header>
  );
}

export function CardBody({ className, ...rest }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cx(styles.body, className)} {...rest} />;
}
