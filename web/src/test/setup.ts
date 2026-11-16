import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach, beforeEach, vi } from "vitest";

import { dropKeptAnswers } from "@/lib/use-async";

// The fixtures are written around the weekend of the event (cut-offs on 15 Nov 2026, deliveries on
// Mon 16 Nov). With the real clock the suite went red on 16 Nov: cut-offs were in the past and
// "today" printed the same day as a fixture. Each test starts at the same moment; a test that
// needs another one sets its own (vi.setSystemTime, or the `now` prop). Only Date is faked, and
// it keeps ticking: code that waits for a Date.now() deadline (products.tsx) must still reach it.
export const TEST_NOW = new Date("2026-11-14T12:00:00+02:00");
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"], now: TEST_NOW, shouldAdvanceTime: true });
});

afterEach(() => {
  cleanup();
  // Sonner replays every active toast to the next Toaster that mounts: clear them,
  // or one test's "saved" toast shows up in the next test.
  toast.dismiss();
  // Kept answers live in the module: one test's list must not open the next test's page.
  dropKeptAnswers();
});

// jsdom has no layout. Radix popper parts (tooltip, select) call these;
// each shim is the no-op jsdom would give if it had layout.
if (!Element.prototype.hasPointerCapture) {
  Element.prototype.hasPointerCapture = () => false;
  Element.prototype.setPointerCapture = () => {};
  Element.prototype.releasePointerCapture = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
// The router restores scroll on navigation; jsdom only logs "not implemented".
window.scrollTo = () => {};
if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as unknown as typeof ResizeObserver;
}
