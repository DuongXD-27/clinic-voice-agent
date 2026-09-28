import { RefreshCw } from "lucide-react";
import { useMemo, useState } from "react";
import { NavLink, Outlet, useSearchParams } from "react-router";

import { PageHeader } from "../../../components/layout/PageHeader";
import { Button } from "../../../components/ui/Button";
import { Segmented } from "../../../components/ui/Segmented";
import { cx } from "../../../lib/cx";
import { obsPaths } from "../model/links";
import { parseRange, RANGE_OPTIONS, toWindow, type RangeHours } from "../model/range";
import type { ObservabilityContext } from "./context";
import styles from "./ObservabilityLayout.module.css";

const RANGE_CHOICES = RANGE_OPTIONS.map((option) => ({
  value: String(option.hours),
  label: option.label,
}));

export function ObservabilityLayout() {
  const [params, setParams] = useSearchParams();
  const range = parseRange(params.get("range"));
  // Mốc cuối của khoảng xem: chốt lúc mở trang, bấm Làm mới hoặc đổi khoảng.
  const [endMs, setEndMs] = useState(() => Date.now());

  const context = useMemo<ObservabilityContext>(() => {
    const window = toWindow(range, endMs);
    return { range, window, windowKey: `${window.start}|${window.end}` };
  }, [range, endMs]);

  const changeRange = (hours: RangeHours) => {
    setParams((current) => {
      const next = new URLSearchParams(current);
      next.set("range", String(hours));
      return next;
    });
    setEndMs(Date.now());
  };

  const tab = ({ isActive }: { isActive: boolean }) => cx(styles.tab, isActive && styles.active);

  return (
    <>
      <PageHeader
        eyebrow="Observability"
        title="Giám sát callbot"
        description="Latency, lỗi và chất lượng từng lượt, đọc từ trace ẩn danh. Chỉ đọc; thời gian theo giờ máy bạn."
        actions={
          <>
            <Segmented
              label="Khoảng thời gian"
              name="obs-range"
              value={String(range)}
              options={RANGE_CHOICES}
              onChange={(value) => {
                changeRange(parseRange(value));
              }}
            />
            <Button
              icon={<RefreshCw />}
              onClick={() => {
                setEndMs(Date.now());
              }}
            >
              Làm mới
            </Button>
          </>
        }
      />
      <nav className={styles.tabs} aria-label="Màn hình observability">
        <NavLink to={obsPaths.overview(range)} end className={tab}>
          Tổng quan
        </NavLink>
        <NavLink to={obsPaths.quality(range)} className={tab}>
          Chất lượng
        </NavLink>
      </nav>
      <Outlet context={context} />
    </>
  );
}
