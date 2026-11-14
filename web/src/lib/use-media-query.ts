import { useCallback, useSyncExternalStore } from "react";

/** Below Tailwind's `md` breakpoint: the widths where a page gets its phone layout. */
export const PHONE_QUERY = "(max-width: 767px)";

function mediaQuery(query: string): MediaQueryList | null {
  return typeof window.matchMedia === "function" ? window.matchMedia(query) : null;
}

/**
 * Whether a CSS media query matches now, kept in step when the window changes.
 * False where there is no `matchMedia` (jsdom), so a test sees the desktop layout.
 * For a layout that renders different elements; a change of classes alone needs only CSS.
 */
export function useMediaQuery(query: string): boolean {
  const subscribe = useCallback(
    (onChange: () => void) => {
      const list = mediaQuery(query);
      list?.addEventListener("change", onChange);
      return () => list?.removeEventListener("change", onChange);
    },
    [query],
  );
  return useSyncExternalStore(subscribe, () => mediaQuery(query)?.matches ?? false);
}
