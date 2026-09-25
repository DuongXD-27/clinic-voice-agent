/**
 * Hình học biểu đồ p95 theo giờ (thuần, test được). Giờ không có mẫu để trống: không nối
 * đường qua khoảng trống để khỏi vẽ ra xu hướng không có thật.
 */

export interface ChartBox {
  width: number;
  height: number;
  left: number;
  top: number;
  bottom: number;
}

export const CHART_BOX: ChartBox = { width: 1000, height: 220, left: 56, top: 16, bottom: 28 };

export interface Point {
  x: number;
  y: number;
  value: number;
  index: number;
}

export interface SeriesGeometry {
  points: Point[];
  /** Đoạn thẳng nối hai giờ liền kề đều có số liệu. */
  segments: [Point, Point][];
}

/** Giá trị lớn nhất trên trục; tối thiểu 1 để trục không chia cho 0. */
export function chartMax(series: readonly (readonly (number | null)[])[]): number {
  const values = series.flat().filter((value): value is number => value !== null);
  return Math.max(1, ...values);
}

export function seriesGeometry(
  values: readonly (number | null)[],
  max: number,
  box: ChartBox = CHART_BOX,
): SeriesGeometry {
  const plotWidth = box.width - box.left - 16;
  const plotHeight = box.height - box.top - box.bottom;
  const x = (index: number) =>
    values.length <= 1
      ? box.left + plotWidth / 2
      : box.left + (index / (values.length - 1)) * plotWidth;
  const y = (value: number) => box.top + plotHeight - (value / max) * plotHeight;

  const points: Point[] = [];
  const segments: [Point, Point][] = [];
  let previous: Point | null = null;
  values.forEach((value, index) => {
    if (value === null) {
      previous = null;
      return;
    }
    const point = { x: x(index), y: y(value), value, index };
    if (previous) segments.push([previous, point]);
    points.push(point);
    previous = point;
  });
  return { points, segments };
}

/** Vị trí các đường lưới ngang: 0, nửa, max. */
export function gridLines(max: number, box: ChartBox = CHART_BOX): { y: number; value: number }[] {
  const plotHeight = box.height - box.top - box.bottom;
  return [0, 0.5, 1].map((ratio) => ({
    y: box.top + plotHeight - ratio * plotHeight,
    value: max * ratio,
  }));
}
