import { useCallback, useEffect, useMemo, useState, type ReactNode } from "react";

import { checkServices, type ServiceSnapshot } from "./api";
import { ServiceStatusContext } from "./serviceStatusContext";

const INITIAL: ServiceSnapshot = {
  health: { state: "checking" },
  readiness: { state: "checking" },
  checkedAt: null,
};

interface Props {
  children: ReactNode;
  /** Chu kỳ kiểm tra lại; mặc định 30 giây. */
  intervalMs?: number;
}

/** Kiểm tra /health và /ready một lần cho cả app, chia sẻ kết quả qua context. */
export function ServiceStatusProvider({ children, intervalMs = 30_000 }: Props) {
  const [snapshot, setSnapshot] = useState(INITIAL);
  const [round, setRound] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    checkServices(controller.signal).then(setSnapshot, () => {
      // Chỉ lỗi huỷ request (đổi vòng hoặc unmount) mới tới đây; vòng sau sẽ cập nhật.
    });
    const timer = window.setTimeout(() => {
      setRound((value) => value + 1);
    }, intervalMs);
    return () => {
      controller.abort();
      window.clearTimeout(timer);
    };
  }, [round, intervalMs]);

  const refresh = useCallback(() => {
    setSnapshot((current) => ({
      ...current,
      health: { state: "checking" },
      readiness: { state: "checking" },
    }));
    setRound((value) => value + 1);
  }, []);

  const value = useMemo(() => ({ ...snapshot, refresh }), [snapshot, refresh]);
  return <ServiceStatusContext value={value}>{children}</ServiceStatusContext>;
}
