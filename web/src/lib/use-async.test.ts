import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/types";
import { isUnreachable, useAsync } from "@/lib/use-async";

describe("useAsync", () => {
  it("keeps the ready data while reloading, then shows the new data", async () => {
    let resolveNext: (value: string) => void = () => {};
    let calls = 0;
    const load = () => {
      calls += 1;
      if (calls === 1) return Promise.resolve("first");
      return new Promise<string>((resolve) => {
        resolveNext = resolve;
      });
    };
    const { result } = renderHook(() => useAsync(load));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    act(() => result.current.reload());
    expect(result.current.status).toBe("ready");
    expect(result.current.data).toBe("first");

    await act(async () => resolveNext("second"));
    expect(result.current.data).toBe("second");
  });

  it("resets to loading when the dependencies change", async () => {
    const load = (key: string) => (key === "a" ? Promise.resolve(key) : new Promise<string>(() => {}));
    const { result, rerender } = renderHook(({ key }) => useAsync(() => load(key), [key]), {
      initialProps: { key: "a" },
    });
    await waitFor(() => expect(result.current.status).toBe("ready"));
    rerender({ key: "b" });
    expect(result.current.status).toBe("loading");
  });

  describe("when the gateway could not be reached", () => {
    beforeEach(() => vi.useFakeTimers());
    afterEach(() => vi.useRealTimers());

    const netError = () => new ApiError("NETWORK", "Could not reach the gateway.");

    it("tries again and ends ready when the second try works", async () => {
      const load = vi.fn().mockRejectedValueOnce(netError()).mockResolvedValue("product");
      const { result } = renderHook(() => useAsync(load));
      expect(result.current.status).toBe("loading");

      await act(async () => vi.advanceTimersByTimeAsync(499));
      expect(load).toHaveBeenCalledTimes(1);
      await act(async () => vi.advanceTimersByTimeAsync(1));

      expect(load).toHaveBeenCalledTimes(2);
      expect(result.current.status).toBe("ready");
      expect(result.current.data).toBe("product");
    });

    it("ends error after three tries when every try fails", async () => {
      const load = vi.fn().mockRejectedValue(netError());
      const { result } = renderHook(() => useAsync(load));

      await act(async () => vi.advanceTimersByTimeAsync(500));
      expect(load).toHaveBeenCalledTimes(2);
      await act(async () => vi.advanceTimersByTimeAsync(1500));
      expect(load).toHaveBeenCalledTimes(3);
      expect(result.current.status).toBe("error");
      await act(async () => vi.advanceTimersByTimeAsync(5000));
      expect(load).toHaveBeenCalledTimes(3);
    });

    it.each([
      ["a contract error", new ApiError("TOTAL_MISMATCH", "Total does not match", {}, 409)],
      ["a plain error", new Error("Bad mapping")],
    ])("shows %s at once", async (_case, error) => {
      const load = vi.fn().mockRejectedValue(error);
      const { result } = renderHook(() => useAsync(load));
      await act(async () => vi.advanceTimersByTimeAsync(0));
      expect(result.current.status).toBe("error");
      await act(async () => vi.advanceTimersByTimeAsync(5000));
      expect(load).toHaveBeenCalledTimes(1);
    });

    it("tries again after a 503", async () => {
      const load = vi.fn().mockRejectedValueOnce(new ApiError("GATEWAY_ERROR", "Restarting", {}, 503)).mockResolvedValue("ok");
      const { result } = renderHook(() => useAsync(load));
      await act(async () => vi.advanceTimersByTimeAsync(500));
      expect(load).toHaveBeenCalledTimes(2);
      expect(result.current.status).toBe("ready");
    });

    it("makes no further call after unmounting during the wait", async () => {
      const load = vi.fn().mockRejectedValue(netError());
      const { unmount } = renderHook(() => useAsync(load));
      await act(async () => vi.advanceTimersByTimeAsync(0));
      expect(load).toHaveBeenCalledTimes(1);
      unmount();
      await act(async () => vi.advanceTimersByTimeAsync(5000));
      expect(load).toHaveBeenCalledTimes(1);
    });

    it("keeps the ready data while a failing reload tries again", async () => {
      const load = vi.fn().mockResolvedValueOnce("first").mockRejectedValueOnce(netError()).mockResolvedValueOnce("second");
      const { result } = renderHook(() => useAsync(load));
      await act(async () => vi.advanceTimersByTimeAsync(0));
      expect(result.current.status).toBe("ready");

      act(() => result.current.reload());
      await act(async () => vi.advanceTimersByTimeAsync(0));
      expect(result.current.status).toBe("ready");
      expect(result.current.data).toBe("first");
      await act(async () => vi.advanceTimersByTimeAsync(500));
      expect(load).toHaveBeenCalledTimes(3);
      expect(result.current.status).toBe("ready");
      expect(result.current.data).toBe("second");
    });
  });

  it("knows which errors mean the gateway could not be reached", () => {
    expect(isUnreachable(new ApiError("NETWORK", ""))).toBe(true);
    expect(isUnreachable(new ApiError("INVALID_RESPONSE", ""))).toBe(true);
    expect(isUnreachable(new ApiError("GATEWAY_ERROR", "", {}, 503))).toBe(true);
    expect(isUnreachable(new ApiError("TOTAL_MISMATCH", "", {}, 409))).toBe(false);
    expect(isUnreachable(new Error("NETWORK"))).toBe(false);
  });
});
