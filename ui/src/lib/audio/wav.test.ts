import { describe, expect, it } from "vitest";

import { encodeWav, mergeFloat32 } from "./wav";

function text(view: DataView, offset: number, length: number): string {
  return String.fromCharCode(...Array.from({ length }, (_, i) => view.getUint8(offset + i)));
}

describe("mergeFloat32", () => {
  it("ghép các khối theo thứ tự", () => {
    const merged = mergeFloat32([
      new Float32Array([1, 2]),
      new Float32Array([]),
      new Float32Array([3]),
    ]);

    expect(Array.from(merged)).toEqual([1, 2, 3]);
  });
});

describe("encodeWav", () => {
  it("ghi header RIFF PCM16 mono đúng tần số", () => {
    const view = new DataView(encodeWav(new Float32Array(10), 16_000));

    expect(view.byteLength).toBe(44 + 20);
    expect(text(view, 0, 4)).toBe("RIFF");
    expect(view.getUint32(4, true)).toBe(36 + 20);
    expect(text(view, 8, 8)).toBe("WAVEfmt ");
    expect(view.getUint16(20, true)).toBe(1); // PCM
    expect(view.getUint16(22, true)).toBe(1); // mono
    expect(view.getUint32(24, true)).toBe(16_000);
    expect(view.getUint32(28, true)).toBe(32_000);
    expect(view.getUint16(34, true)).toBe(16);
    expect(text(view, 36, 4)).toBe("data");
    expect(view.getUint32(40, true)).toBe(20);
  });

  it("đổi float sang int16 và cắt mẫu ngoài [-1, 1]", () => {
    const view = new DataView(encodeWav(new Float32Array([-2, -1, 0, 1, 2]), 8_000));
    const samples = [0, 1, 2, 3, 4].map((i) => view.getInt16(44 + i * 2, true));

    expect(samples).toEqual([-32768, -32768, 0, 32767, 32767]);
  });
});
