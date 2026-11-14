import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { toast } from "sonner";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
  // Sonner replays every active toast to the next Toaster that mounts: clear them,
  // or one test's "saved" toast shows up in the next test.
  toast.dismiss();
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
