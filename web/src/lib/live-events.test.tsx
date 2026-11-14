import { act, render, renderHook, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ApiProvider } from "@/api";
import { createMockApi } from "@/api/mock";
import type { LiveEvent } from "@/api/types";
import { LiveEventsProvider, useLiveEvents } from "@/lib/live-events";
import { useAsync } from "@/lib/use-async";

afterEach(() => vi.useRealTimers());

it("debounces changes and reloads again after every connect", async () => {
  vi.useFakeTimers();
  let publish: ((event: LiveEvent) => void) | undefined;
  let status: ((connected: boolean) => void) | undefined;
  const api = createMockApi();
  api.subscribeEvents = (onEvent, onStatus) => {
    publish = onEvent;
    status = onStatus;
    return () => {};
  };
  const changes = vi.fn();
  function Probe() {
    useLiveEvents(["proposal"], changes);
    return null;
  }
  render(<ApiProvider api={api}><LiveEventsProvider><Probe /></LiveEventsProvider></ApiProvider>);
  await act(async () => { status?.(true); });
  await act(async () => {
    publish?.({ kind: "proposal", operation: "insert" });
    publish?.({ kind: "approval", operation: "update" });
    publish?.({ kind: "proposal", operation: "update" });
    await vi.advanceTimersByTimeAsync(299);
  });
  expect(changes).not.toHaveBeenCalled();
  await act(async () => { await vi.advanceTimersByTimeAsync(1); });
  expect(changes).toHaveBeenCalledTimes(1);
  await act(async () => { status?.(false); });
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
  expect(changes).toHaveBeenCalledTimes(1);
  await act(async () => { status?.(true); });
  await act(async () => { await vi.advanceTimersByTimeAsync(300); });
  expect(changes).toHaveBeenCalledTimes(2);
});

it("forgets the kept answers of read-only pages on a live event and on a new connection", async () => {
  let publish: ((event: LiveEvent) => void) | undefined;
  let status: ((connected: boolean) => void) | undefined;
  const api = createMockApi();
  api.subscribeEvents = (onEvent, onStatus) => {
    publish = onEvent;
    status = onStatus;
    return () => {};
  };
  render(<ApiProvider api={api}><LiveEventsProvider><span /></LiveEventsProvider></ApiProvider>);
  const never = () => new Promise<string>(() => {});
  const keepOne = async () => {
    const page = renderHook(() => useAsync(() => Promise.resolve("kept"), [], { keep: "list" }));
    await waitFor(() => expect(page.result.current.status).toBe("ready"));
    page.unmount();
  };

  await keepOne();
  await act(async () => { publish?.({ kind: "audit", operation: "insert" }); });
  expect(renderHook(() => useAsync(never, [], { keep: "list" })).result.current.status).toBe("loading");

  await keepOne();
  await act(async () => { status?.(true); });
  expect(renderHook(() => useAsync(never, [], { keep: "list" })).result.current.status).toBe("loading");
});
