import type { Aggregation, QualityComponent } from "./types";

export type QualityView = "numbers" | "charts" | "both";

export interface QualitySettings {
  component: QualityComponent;
  view: QualityView;
  aggregation: Aggregation;
  /** Lọc bảng ví dụ theo một loại vấn đề. */
  issue: string | null;
}

const COMPONENTS: readonly QualityComponent[] = ["STT", "TTS"];
const VIEWS: readonly QualityView[] = ["numbers", "charts", "both"];
const AGGREGATIONS: readonly Aggregation[] = ["call", "turn"];

function pick<T extends string>(options: readonly T[], value: string | null, fallback: T): T {
  return options.find((option) => option === value) ?? fallback;
}

/** Đọc từ URL (`?component=&view=&aggregation=&issue=`); giá trị lạ về mặc định. */
export function parseQuality(params: URLSearchParams): QualitySettings {
  return {
    component: pick(COMPONENTS, params.get("component")?.toUpperCase() ?? null, "STT"),
    view: pick(VIEWS, params.get("view"), "both"),
    aggregation: pick(AGGREGATIONS, params.get("aggregation"), "call"),
    issue: params.get("issue") || null,
  };
}

export function unitOf(aggregation: Aggregation): string {
  return aggregation === "call" ? "cuộc gọi" : "lượt";
}
