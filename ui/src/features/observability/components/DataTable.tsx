import type { ReactNode } from "react";

import { cx } from "../../../lib/cx";
import styles from "./DataTable.module.css";

export interface Column<T> {
  header: string;
  cell: (row: T) => ReactNode;
  numeric?: boolean;
  /** Ô đầu dòng: <th scope="row"> để trình đọc màn hình đọc kèm. */
  rowHeader?: boolean;
}

interface Props<T> {
  /** Tên bảng cho trình đọc màn hình. */
  label: string;
  columns: readonly Column<T>[];
  rows: readonly T[];
  rowKey: (row: T, index: number) => string;
}

export function DataTable<T>({ label, columns, rows, rowKey }: Props<T>) {
  return (
    <div className={styles.wrap}>
      <table className={styles.table} aria-label={label}>
        <thead>
          <tr>
            {columns.map((column) => (
              <th key={column.header} scope="col" className={cx(column.numeric && styles.numeric)}>
                {column.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={rowKey(row, index)}>
              {columns.map((column) => {
                const className = cx(column.numeric && styles.numeric);
                return column.rowHeader ? (
                  <th key={column.header} scope="row" className={className}>
                    {column.cell(row)}
                  </th>
                ) : (
                  <td key={column.header} className={className}>
                    {column.cell(row)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
