import { describe, expect, it } from "vitest";

import { appointmentOptions, fixturesHint, phoneOptions, type FixturesState } from "./fixtures";

const ready: FixturesState = {
  status: "ready",
  data: {
    source: "mock",
    appointments: [
      { appointment_id: "apt_00417", status: "SCHEDULED", display_name: "N. V. A." },
      { appointment_id: "apt_00418", status: null, display_name: null },
    ],
    phones: [{ phone: "0912345600", display_name: "N. V. A." }],
  },
};

describe("appointmentOptions", () => {
  it("ghép id, trạng thái và tên", () => {
    expect(appointmentOptions(ready, "apt_00417")).toEqual([
      { value: "apt_00417", label: "apt_00417 · SCHEDULED · N. V. A." },
      { value: "apt_00418", label: "apt_00418" },
    ]);
  });

  it("vẫn có lựa chọn đang chọn và lịch mặc định khi fixtures lỗi", () => {
    const options = appointmentOptions({ status: "error", message: "HTTP 404" }, "apt_custom");

    expect(options.map((option) => option.value)).toEqual(["apt_custom", "apt_00417"]);
  });
});

describe("phoneOptions", () => {
  it("rỗng khi chưa tải xong", () => {
    expect(phoneOptions({ status: "loading" })).toEqual([]);
  });

  it("ghép số và tên", () => {
    expect(phoneOptions(ready)).toEqual([{ value: "0912345600", label: "0912345600 · N. V. A." }]);
  });
});

describe("fixturesHint", () => {
  it("tóm tắt nguồn và số lượng", () => {
    expect(fixturesHint(ready)).toBe("Nguồn: clinic mock · 2 lịch hẹn · 1 số điện thoại");
  });

  it("báo lỗi nhưng vẫn cho nhập tay", () => {
    expect(fixturesHint({ status: "error", message: "HTTP 404" })).toContain("Vẫn nhập tay được");
  });
});
