import { describe, expect, it } from "vitest";

import { overview } from "../test/fixtures";
import { chartMax, gridLines, seriesGeometry } from "./chart";
import {
  displayLabel,
  formatCount,
  formatDuration,
  formatRate,
  formatTimestamp,
  NO_DATA,
} from "./format";
import { obsPaths } from "./links";
import { kpiCards, parseMetric, parseSlowThreshold } from "./overview";
import { parseQuality } from "./quality";
import { parseRange, toWindow } from "./range";

describe("format", () => {
  it.each([
    [null, NO_DATA],
    [Number.NaN, NO_DATA],
    [0, "0 ms"],
    [850, "850 ms"],
    [1500, "1,5 s"],
  ])("formatDuration(%s) = %s", (value, expected) => {
    expect(formatDuration(value)).toBe(expected);
  });

  it("tỷ lệ và số đếm; thiếu dữ liệu hiện gạch, không hiện 0", () => {
    expect(formatRate(0.0476)).toBe("4,8%");
    expect(formatRate(null)).toBe(NO_DATA);
    expect(formatCount(12_345)).toBe("12.345");
    expect(formatCount(undefined)).toBe(NO_DATA);
  });

  it("thời điểm lỗi và nhãn trống", () => {
    expect(formatTimestamp("không phải ngày")).toBe(NO_DATA);
    expect(formatTimestamp(null)).toBe(NO_DATA);
    expect(displayLabel("  ")).toBe("UNSPECIFIED");
    expect(displayLabel("vbee")).toBe("vbee");
  });
});

describe("range", () => {
  it("chỉ nhận 1 / 24 / 168 giờ, còn lại về 24", () => {
    expect(parseRange("1")).toBe(1);
    expect(parseRange("168")).toBe(168);
    expect(parseRange("5")).toBe(24);
    expect(parseRange(null)).toBe(24);
  });

  it("tính khoảng ngược từ mốc cuối", () => {
    expect(toWindow(1, Date.parse("2026-09-25T10:00:00Z"))).toEqual({
      start: "2026-09-25T09:00:00.000Z",
      end: "2026-09-25T10:00:00.000Z",
    });
  });
});

describe("overview", () => {
  it("7 thẻ KPI theo thứ tự, p95 và ngữ cảnh mẫu", () => {
    const cards = kpiCards(overview);

    expect(cards.map((card) => card.metric)).toEqual([
      "turn",
      "stt",
      "core",
      "tts",
      "error",
      "slow_turn",
      "empty_transcript",
    ]);
    expect(cards[1]).toMatchObject({
      label: "STT observation",
      value: "800 ms",
      context: "p95 · 10 mẫu",
    });
    expect(cards[4]).toMatchObject({ value: "4,8%", context: "2 / 42 lượt" });
  });

  it("thẻ không có mẫu được đánh dấu", () => {
    const card = kpiCards({
      ...overview,
      stt_latency: { ...overview.stt_latency, p95_ms: null },
    })[1];

    expect(card).toMatchObject({ value: NO_DATA, hasData: false });
  });

  it("đọc metric và ngưỡng lượt chậm từ URL", () => {
    expect(parseMetric("tts")).toBe("tts");
    expect(parseMetric("khác")).toBeNull();
    expect(parseSlowThreshold("3000")).toBe(3000);
    expect(parseSlowThreshold("1234")).toBe(2000);
  });
});

describe("chart", () => {
  it("không nối đường qua giờ thiếu số liệu", () => {
    const geometry = seriesGeometry([100, null, 300, 200], 300);

    expect(geometry.points.map((point) => point.index)).toEqual([0, 2, 3]);
    expect(geometry.segments.map(([from, to]) => [from.index, to.index])).toEqual([[2, 3]]);
  });

  it("giá trị lớn nằm cao hơn, một điểm đặt giữa trục", () => {
    const [low, high] = seriesGeometry([100, 300], 300).points;
    const single = seriesGeometry([50], 100).points[0];

    expect(high?.y).toBeLessThan(low?.y ?? 0);
    expect(single?.x).toBeGreaterThan(400);
  });

  it("trục tối thiểu 1 và lưới 0 / nửa / max", () => {
    expect(chartMax([[null], []])).toBe(1);
    expect(chartMax([[5, null], [9]])).toBe(9);
    expect(gridLines(200).map((line) => line.value)).toEqual([0, 100, 200]);
  });
});

describe("quality", () => {
  it("đọc cài đặt từ URL, giá trị lạ về mặc định", () => {
    expect(
      parseQuality(new URLSearchParams("component=tts&view=charts&aggregation=turn&issue=X")),
    ).toEqual({
      component: "TTS",
      view: "charts",
      aggregation: "turn",
      issue: "X",
    });
    expect(parseQuality(new URLSearchParams("component=llm&view=x"))).toEqual({
      component: "STT",
      view: "both",
      aggregation: "call",
      issue: null,
    });
  });
});

describe("links", () => {
  it("giữ khoảng thời gian và mã hoá tham số", () => {
    expect(obsPaths.overview(24, { metric: "stt" })).toBe("/observability?range=24&metric=stt");
    expect(obsPaths.call(1, "call/ab")).toBe("/observability/calls/call%2Fab?range=1");
    expect(obsPaths.turn(24, "t1", "c1")).toBe("/observability/turns/t1?range=24&call=c1");
    expect(obsPaths.turn(24, "t1", null)).toBe("/observability/turns/t1?range=24");
  });
});
