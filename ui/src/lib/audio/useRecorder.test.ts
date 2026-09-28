import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useRecorder } from "./useRecorder";

/** Mic giả: getUserMedia chờ tới khi test gọi `grant()`, như lúc hộp xin quyền còn mở. */
function fakeMic() {
  const tracks: { stop: ReturnType<typeof vi.fn> }[] = [];
  const pending: (() => void)[] = [];
  const getUserMedia = vi.fn(
    () =>
      new Promise<MediaStream>((resolve) => {
        pending.push(() => {
          const track = { stop: vi.fn() };
          tracks.push(track);
          resolve({ getTracks: () => [track] } as unknown as MediaStream);
        });
      }),
  );
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia },
  });
  return {
    getUserMedia,
    tracks,
    grant: () => {
      for (const resolve of pending.splice(0)) resolve();
    },
  };
}

class FakeAudioContext {
  sampleRate = 48_000;
  audioWorklet = { addModule: vi.fn(() => Promise.resolve()) };
  close = vi.fn(() => Promise.resolve());
  createMediaStreamSource = vi.fn(() => ({ connect: vi.fn(), disconnect: vi.fn() }));
}

class FakeWorkletNode {
  port = { onmessage: null, postMessage: vi.fn() };
  disconnect = vi.fn();
}

beforeEach(() => {
  vi.stubGlobal("AudioContext", FakeAudioContext);
  vi.stubGlobal("AudioWorkletNode", FakeWorkletNode);
});

afterEach(() => {
  vi.unstubAllGlobals();
  Reflect.deleteProperty(navigator, "mediaDevices");
});

describe("useRecorder", () => {
  it("bấm Ghi âm hai lần khi đang xin quyền: chỉ mở một stream", async () => {
    const mic = fakeMic();
    const { result } = renderHook(() => useRecorder());

    await act(async () => {
      const first = result.current.start();
      const second = result.current.start();
      mic.grant();
      await Promise.all([first, second]);
    });

    expect(mic.getUserMedia).toHaveBeenCalledTimes(1);
    expect(result.current.state.status).toBe("recording");
  });

  it("clear trong lúc xin quyền: tắt mic vừa mở, không chuyển sang recording", async () => {
    const mic = fakeMic();
    const { result } = renderHook(() => useRecorder());

    await act(async () => {
      const starting = result.current.start();
      result.current.clear();
      mic.grant();
      await starting;
    });

    expect(mic.tracks[0]?.stop).toHaveBeenCalled();
    expect(result.current.state.status).toBe("idle");
  });

  it("rời trang trong lúc xin quyền: tắt mic vừa mở", async () => {
    const mic = fakeMic();
    const { result, unmount } = renderHook(() => useRecorder());

    let starting: Promise<void> = Promise.resolve();
    act(() => {
      starting = result.current.start();
    });
    unmount();
    mic.grant();
    await starting;

    expect(mic.tracks[0]?.stop).toHaveBeenCalled();
  });
});
