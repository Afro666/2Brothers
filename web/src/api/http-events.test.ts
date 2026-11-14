import { waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createEventsHttp } from "@/api/http-events";
import type { LiveEvent } from "@/api/types";

const encoder = new TextEncoder();

function stream(chunks: string[] = [], close = false) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(encoder.encode(chunk)));
      if (close) controller.close();
    },
  });
}

function subscribe(onEvent: (event: LiveEvent) => void = () => {}, onStatus?: (connected: boolean) => void) {
  return createEventsHttp("/api/", "/v1/kitchens/demo-kitchen", () => null).subscribeEvents!(onEvent, onStatus);
}

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("HTTP event stream", () => {
  it("parses split messages and ignores comments, unknown events and bad JSON", async () => {
    const fetchMock = vi.fn(async () => new Response(stream([
      ": connected\n\nevent: proposal\ndata: {\"operation\":\"in",
      "sert\"}\n\n: ping\n\nevent: other\ndata: {\"operation\":\"update\"}\n\nevent: audit\ndata: not-json\n\nevent: approval\ndata: {\"operation\":\"replace\"}\n\n",
    ], true)));
    vi.stubGlobal("fetch", fetchMock);
    const events: LiveEvent[] = [];
    const stop = subscribe((event) => events.push(event));

    await waitFor(() => expect(events).toEqual([
      { kind: "proposal", operation: "insert" },
      { kind: "approval", operation: "replace" },
    ]));
    expect(fetchMock).toHaveBeenCalledWith("/api/v1/kitchens/demo-kitchen/events", expect.objectContaining({
      credentials: "same-origin",
      headers: { "X-User": "human" },
    }));
    stop();
  });

  it("reconnects two seconds after the stream ends", async () => {
    vi.useFakeTimers();
    const first = stream([": connected\n\n"], true);
    vi.stubGlobal("fetch", vi.fn()
      .mockImplementationOnce(async () => new Response(first))
      .mockImplementationOnce(async () => new Response(stream())));
    const statuses: boolean[] = [];
    const stop = subscribe(() => {}, (connected) => statuses.push(connected));

    await vi.advanceTimersByTimeAsync(0);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(statuses).toEqual([true, false]);
    await vi.advanceTimersByTimeAsync(1_999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(statuses).toEqual([true, false, true]);
    stop();
  });

  it.each([401, 403, 503])("stops permanently after HTTP %s", async (status) => {
    vi.useFakeTimers();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(null, { status })));
    const onStatus = vi.fn();
    const stop = subscribe(() => {}, onStatus);
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(onStatus).toHaveBeenCalledWith(false);
    stop();
  });

  it("stop aborts the request and prevents reconnects", async () => {
    vi.useFakeTimers();
    let signal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
      signal = init.signal as AbortSignal;
      return new Response(stream());
    }));
    const stop = subscribe();
    await vi.advanceTimersByTimeAsync(0);
    expect(signal?.aborted).toBe(false);
    stop();
    expect(signal?.aborted).toBe(true);
    await vi.advanceTimersByTimeAsync(10_000);
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("closes while hidden and opens again when visible", async () => {
    const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false);
    let firstSignal: AbortSignal | undefined;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init: RequestInit) => {
      firstSignal ??= init.signal as AbortSignal;
      return new Response(stream());
    }));
    const stop = subscribe();
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));

    hidden.mockReturnValue(true);
    document.dispatchEvent(new Event("visibilitychange"));
    expect(firstSignal?.aborted).toBe(true);
    hidden.mockReturnValue(false);
    document.dispatchEvent(new Event("visibilitychange"));
    await waitFor(() => expect(fetch).toHaveBeenCalledTimes(2));
    stop();
  });
});
