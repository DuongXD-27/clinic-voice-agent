import { useEffect, useEffectEvent, useState } from "react";

export type QueryState<T> =
  { status: "loading" } | { status: "ready"; data: T } | { status: "error"; message: string };

const LOADING = { status: "loading" } as const;

/**
 * Tải dữ liệu theo `key`: key đổi (khoảng thời gian, trang, bộ lọc…) thì huỷ request cũ và tải
 * lại; response của key cũ đến muộn không ghi đè. `fetcher` đọc giá trị mới nhất mà không cần
 * nằm trong deps.
 */
export function useQuery<T>(key: string, fetcher: (signal: AbortSignal) => Promise<T>) {
  const [result, setResult] = useState<{ key: string; state: QueryState<T> } | null>(null);
  const load = useEffectEvent(fetcher);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then(
      (data) => {
        setResult({ key, state: { status: "ready", data } });
      },
      (error: unknown) => {
        if (controller.signal.aborted) return;
        const message = error instanceof Error ? error.message : "Không tải được dữ liệu.";
        setResult({ key, state: { status: "error", message } });
      },
    );
    return () => {
      controller.abort();
    };
  }, [key]);

  return result?.key === key ? result.state : LOADING;
}
