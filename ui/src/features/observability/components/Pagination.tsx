import { Button } from "../../../components/ui/Button";
import { formatCount } from "../model/format";
import styles from "./Pagination.module.css";

interface Props {
  offset: number;
  /** Số dòng của trang hiện tại. */
  count: number;
  hasNext: boolean;
  pageSize: number;
  onChange: (offset: number) => void;
  total?: number;
}

export function Pagination({ offset, count, hasNext, pageSize, onChange, total }: Props) {
  const from = count ? offset + 1 : 0;
  return (
    <div className={styles.pagination}>
      <Button
        size="sm"
        disabled={offset === 0}
        onClick={() => {
          onChange(Math.max(0, offset - pageSize));
        }}
      >
        Trước
      </Button>
      <span>
        {formatCount(from)}–{formatCount(offset + count)}
        {total === undefined ? "" : ` / ${formatCount(total)}`}
      </span>
      <Button
        size="sm"
        disabled={!hasNext}
        onClick={() => {
          onChange(offset + pageSize);
        }}
      >
        Sau
      </Button>
    </div>
  );
}
