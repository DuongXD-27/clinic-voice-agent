/** Đường dẫn trong mục Observability; luôn mang `?range=` để giữ khoảng thời gian đang xem. */

function withQuery(path: string, params: Record<string, string | number | null | undefined>) {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") query.set(key, String(value));
  }
  const text = query.toString();
  return text ? `${path}?${text}` : path;
}

export const obsPaths = {
  overview: (range: number, extra: { metric?: string | null; slow?: number | null } = {}) =>
    withQuery("/observability", { range, metric: extra.metric, slow: extra.slow }),
  quality: (range: number, extra: Record<string, string | null> = {}) =>
    withQuery("/observability/quality", { range, ...extra }),
  call: (range: number, callKey: string) =>
    withQuery(`/observability/calls/${encodeURIComponent(callKey)}`, { range }),
  turn: (range: number, traceId: string, callKey?: string | null) =>
    withQuery(`/observability/turns/${encodeURIComponent(traceId)}`, { range, call: callKey }),
};
