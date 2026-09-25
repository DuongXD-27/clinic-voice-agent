import { useCallback, useEffect, useState } from "react";

import { getClinicFixtures } from "./api";
import type { FixturesState } from "./model/fixtures";

/** Tải danh sách lịch hẹn / số điện thoại; tải lại khi đổi API key hoặc gọi `reload()`. */
export function useClinicFixtures(apiKey: string) {
  const [state, setState] = useState<FixturesState>({ status: "loading" });
  const [round, setRound] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    getClinicFixtures(apiKey, controller.signal).then(
      (data) => {
        setState({ status: "ready", data });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: "error", message: error instanceof Error ? error.message : "lỗi" });
      },
    );
    return () => {
      controller.abort();
    };
  }, [apiKey, round]);

  const reload = useCallback(() => {
    setState({ status: "loading" });
    setRound((value) => value + 1);
  }, []);

  return { fixtures: state, reload };
}
