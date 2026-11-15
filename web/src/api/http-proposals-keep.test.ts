import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

/** A gateway with no proposals; counts how often the list is asked. */
function gateway() {
  const asked = { proposals: 0 };
  vi.stubGlobal("fetch", async (url: string) => {
    if (String(url).endsWith("/proposals")) asked.proposals += 1;
    const body = String(url).endsWith("/proposals") ? { proposals: [] } : { events: [] };
    return new Response(JSON.stringify(body), { status: 200 });
  });
  return asked;
}

describe("the proposals list of one page load (#1944)", () => {
  it("is asked once for calls that follow each other, and again after 3 seconds", async () => {
    vi.useFakeTimers();
    const asked = gateway();
    const api = createHttpApi("/api");
    await api.listApprovals();
    await api.countPendingApprovals!();
    expect(asked.proposals).toBe(1);
    await vi.advanceTimersByTimeAsync(3000);
    await api.listApprovals();
    expect(asked.proposals).toBe(2);
  });

  it("is asked again at once after a write", async () => {
    const asked = gateway();
    const api = createHttpApi("/api");
    await api.listApprovals();
    // Any write drops the kept list; this one fails on the stub's answer, which is enough.
    await api.reject("p-1", "no", "human").catch(() => undefined);
    await api.listApprovals();
    expect(asked.proposals).toBe(2);
  });
});
