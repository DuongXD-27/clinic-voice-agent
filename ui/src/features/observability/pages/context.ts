import { useOutletContext } from "react-router";

import type { RangeHours, TimeWindow } from "../model/range";

export interface ObservabilityContext {
  range: RangeHours;
  window: TimeWindow;
  /** Đổi khi đổi khoảng hoặc bấm Làm mới: đưa vào key của useQuery để tải lại. */
  windowKey: string;
}

/** Khoảng thời gian chung do ObservabilityLayout cung cấp cho các trang con. */
export function useObservability(): ObservabilityContext {
  return useOutletContext<ObservabilityContext>();
}
