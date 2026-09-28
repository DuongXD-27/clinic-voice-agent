import { describe, expect, it } from "vitest";

import type { Probe } from "./api";
import { describeOverall, describeProbe } from "./describe";

const up: Probe = { state: "up" };
const checking: Probe = { state: "checking" };
const down: Probe = { state: "down", code: "NETWORK_ERROR", message: "Không kết nối được" };

function overall(health: Probe, readiness: Probe) {
  return describeOverall({ health, readiness, checkedAt: null });
}

describe("describeOverall", () => {
  it.each([
    ["đang kiểm tra", checking, up, "neutral", "Đang kiểm tra…"],
    ["API chết thì bỏ qua /ready", down, down, "danger", "Mất kết nối API"],
    ["API sống nhưng session store lỗi", up, down, "warning", "Session store lỗi"],
    ["mọi thứ ổn", up, up, "success", "Hệ thống hoạt động"],
  ] as const)("%s", (_name, health, readiness, tone, label) => {
    expect(overall(health, readiness)).toMatchObject({ tone, label });
  });

  it("chỉ nhấp nháy khi đang kiểm tra", () => {
    expect(overall(checking, checking).pulse).toBe(true);
    expect(overall(up, up).pulse).toBe(false);
  });
});

describe("describeProbe", () => {
  it("ưu tiên mã lỗi, không có thì dùng message", () => {
    expect(describeProbe(down, "OK").label).toBe("NETWORK_ERROR");
    expect(describeProbe({ state: "down", code: null, message: "HTTP 503" }, "OK").label).toBe(
      "HTTP 503",
    );
  });

  it("dùng nhãn riêng khi up", () => {
    expect(describeProbe(up, "Sẵn sàng")).toEqual({
      tone: "success",
      label: "Sẵn sàng",
      pulse: false,
    });
  });
});
