import { act, render } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { ApiProvider } from "@/api";
import { createMockApi } from "@/api/mock";
import type { LiveEvent } from "@/api/types";
import { LiveEventsProvider, useLiveEvents } from "@/lib/live-events";

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
