import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api/types";
import { gatewayRequest } from "@/api/http";
import { createMockApi } from "@/api/mock";
import { dropKeptAnswers, isUnreachable, useAsync } from "@/lib/use-async";
import { confirmedDemoApproval } from "@/mocks/milk-case";

const MOCK_DECISION = {
  approvalId: confirmedDemoApproval.id,
  approvalRef: confirmedDemoApproval.approvalRef,
  expectedTotalExVat: confirmedDemoApproval.totalExVat,
  expectedTotalInclVat: confirmedDemoApproval.totalInclVat,
};

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

    act(() => { result.current.reload(); });
    expect(result.current.status).toBe("ready");
    expect(result.current.data).toBe("first");

    await act(async () => resolveNext("second"));
    expect(result.current.data).toBe("second");
  });

  it("answers a reload only after the new data has arrived", async () => {
    let resolveNext: (value: string) => void = () => {};
    const load = vi.fn()
      .mockResolvedValueOnce("first")
      .mockImplementationOnce(() => new Promise<string>((resolve) => { resolveNext = resolve; }));
    const { result } = renderHook(() => useAsync(load));
    await waitFor(() => expect(result.current.status).toBe("ready"));

    let reloaded = false;
    const waiting = result.current.reload().then(() => { reloaded = true; });
    await act(async () => { await Promise.resolve(); });
    expect(reloaded).toBe(false);

    await act(async () => resolveNext("second"));
    await waiting;
    expect(reloaded).toBe(true);
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
      expect(result.current.status).toBe("loading");
      await act(async () => vi.advanceTimersByTimeAsync(1499));
      expect(result.current.status).toBe("loading");
      await act(async () => vi.advanceTimersByTimeAsync(1));
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

    it("drops a waiting retry when the dependencies change", async () => {
      const load = vi.fn((key: string) => (key === "a" ? Promise.reject(netError()) : Promise.resolve(key)));
      const { result, rerender } = renderHook(({ key }) => useAsync(() => load(key), [key]), {
        initialProps: { key: "a" },
      });
      await act(async () => vi.advanceTimersByTimeAsync(100));
      rerender({ key: "b" });
      await act(async () => vi.advanceTimersByTimeAsync(5000));
      expect(load.mock.calls.map(([key]) => key)).toEqual(["a", "b"]);
      expect(result.current.data).toBe("b");
    });

    it("keeps the ready data while a failing reload tries again", async () => {
      const load = vi.fn().mockResolvedValueOnce("first").mockRejectedValueOnce(netError()).mockResolvedValueOnce("second");
      const { result } = renderHook(() => useAsync(load));
      await act(async () => vi.advanceTimersByTimeAsync(0));
      expect(result.current.status).toBe("ready");

      act(() => { result.current.reload(); });
      await act(async () => vi.advanceTimersByTimeAsync(0));
      expect(result.current.status).toBe("ready");
      expect(result.current.data).toBe("first");
      await act(async () => vi.advanceTimersByTimeAsync(500));
      expect(load).toHaveBeenCalledTimes(3);
      expect(result.current.status).toBe("ready");
      expect(result.current.data).toBe("second");
    });
  });

  describe("with a kept answer", () => {
    afterEach(() => {
      dropKeptAnswers();
      vi.unstubAllGlobals();
    });

    it("shows the kept answer at once on the next visit, then the new answer", async () => {
      const first = renderHook(() => useAsync(() => Promise.resolve("first"), [], { keep: "list" }));
      await waitFor(() => expect(first.result.current.status).toBe("ready"));
      first.unmount();

      let answer: (value: string) => void = () => {};
      const load = vi.fn(() => new Promise<string>((resolve) => (answer = resolve)));
      const second = renderHook(() => useAsync(load, [], { keep: "list" }));
      expect(second.result.current.status).toBe("ready");
      expect(second.result.current.data).toBe("first");
      expect(load).toHaveBeenCalledTimes(1);

      await act(async () => answer("second"));
      expect(second.result.current.data).toBe("second");
    });

    it("starts from loading without a key, and for another key", async () => {
      const first = renderHook(() => useAsync(() => Promise.resolve("first"), [], { keep: "list" }));
      await waitFor(() => expect(first.result.current.status).toBe("ready"));
      first.unmount();
      const never = () => new Promise<string>(() => {});
      expect(renderHook(() => useAsync(never)).result.current.status).toBe("loading");
      expect(renderHook(() => useAsync(never, [], { keep: "other" })).result.current.status).toBe("loading");
    });

    it("forgets every kept answer after a write through the gateway", async () => {
      const first = renderHook(() => useAsync(() => Promise.resolve("first"), [], { keep: "list" }));
      await waitFor(() => expect(first.result.current.status).toBe("ready"));
      first.unmount();

      vi.stubGlobal("fetch", () => Promise.resolve(new Response("{}")));
      await gatewayRequest("/api", "/v1/kitchens/demo-kitchen/proposals", { method: "POST", body: "{}" });

      const second = renderHook(() => useAsync(() => new Promise<string>(() => {}), [], { keep: "list" }));
      expect(second.result.current.status).toBe("loading");
    });

    it("forgets every kept answer after a write to the mock api, and keeps them after a mock read", async () => {
      const api = createMockApi();
      const first = renderHook(() => useAsync(() => api.listOrders(), [], { keep: "orders" }));
      await waitFor(() => expect(first.result.current.status).toBe("ready"));
      first.unmount();

      await api.listApprovals();
      const never = () => new Promise<never>(() => {});
      const kept = renderHook(() => useAsync(never, [], { keep: "orders" }));
      expect(kept.result.current.status).toBe("ready");
      kept.unmount();

      await api.approve(MOCK_DECISION, "human");

      const second = renderHook(() => useAsync(never, [], { keep: "orders" }));
      expect(second.result.current.status).toBe("loading");
    });

    it("keeps the answers after a read through the gateway", async () => {
      const first = renderHook(() => useAsync(() => Promise.resolve("first"), [], { keep: "list" }));
      await waitFor(() => expect(first.result.current.status).toBe("ready"));
      first.unmount();

      vi.stubGlobal("fetch", () => Promise.resolve(new Response("{}")));
      await gatewayRequest("/api", "/v1/kitchens/demo-kitchen/orders");

      const second = renderHook(() => useAsync(() => new Promise<string>(() => {}), [], { keep: "list" }));
      expect(second.result.current.data).toBe("first");
    });

    it("does not put back the answer of a load that began before the drop", async () => {
      let answer: (value: string) => void = () => {};
      const first = renderHook(() =>
        useAsync(() => new Promise<string>((resolve) => (answer = resolve)), [], { keep: "list" }),
      );
      dropKeptAnswers();
      await act(async () => answer("from before the write"));
      expect(first.result.current.data).toBe("from before the write");
      first.unmount();

      const second = renderHook(() => useAsync(() => new Promise<string>(() => {}), [], { keep: "list" }));
      expect(second.result.current.status).toBe("loading");
    });

    it("lets only the newest load for a key change the kept answer", async () => {
      let answerOld: (value: string) => void = () => {};
      const old = renderHook(() =>
        useAsync(() => new Promise<string>((resolve) => (answerOld = resolve)), [], { keep: "list" }),
      );
      old.unmount();
      const newer = renderHook(() => useAsync(() => Promise.resolve("newer"), [], { keep: "list" }));
      await waitFor(() => expect(newer.result.current.data).toBe("newer"));
      newer.unmount();
      await act(async () => answerOld("older, answered late"));

      const next = renderHook(() => useAsync(() => new Promise<string>(() => {}), [], { keep: "list" }));
      expect(next.result.current.data).toBe("newer");
    });

    it("forgets the kept answers when a request is answered 401", async () => {
      const first = renderHook(() => useAsync(() => Promise.resolve("first"), [], { keep: "list" }));
      await waitFor(() => expect(first.result.current.status).toBe("ready"));
      first.unmount();

      vi.stubGlobal("fetch", () =>
        Promise.resolve(new Response(JSON.stringify({ error: { code: "UNAUTHENTICATED", message: "Sign in." } }), { status: 401 })),
      );
      await expect(gatewayRequest("/api", "/v1/kitchens/demo-kitchen/orders")).rejects.toBeTruthy();

      const second = renderHook(() => useAsync(() => new Promise<string>(() => {}), [], { keep: "list" }));
      expect(second.result.current.status).toBe("loading");
    });

    it("shows the error and forgets the kept answer when the new load fails", async () => {
      const first = renderHook(() => useAsync(() => Promise.resolve("first"), [], { keep: "list" }));
      await waitFor(() => expect(first.result.current.status).toBe("ready"));
      first.unmount();

      const second = renderHook(() => useAsync(() => Promise.reject(new Error("Bad mapping")), [], { keep: "list" }));
      expect(second.result.current.data).toBe("first");
      await waitFor(() => expect(second.result.current.status).toBe("error"));
      expect(second.result.current.data).toBeNull();
      second.unmount();

      const third = renderHook(() => useAsync(() => new Promise<string>(() => {}), [], { keep: "list" }));
      expect(third.result.current.status).toBe("loading");
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
