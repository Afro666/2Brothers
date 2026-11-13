import { act, renderHook, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { useAsync } from "@/lib/use-async";

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
});
