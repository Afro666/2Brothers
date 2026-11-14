import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/api/types";

export type AsyncState<T> =
  | { status: "loading"; data: null; error: null; reload: () => void }
  | { status: "error"; data: null; error: Error; reload: () => void }
  | { status: "ready"; data: T; error: null; reload: () => void };
/** Retry delays for a load whose request may have been lost in the venue wifi or a deploy restart. */
const RETRY_DELAYS_MS = [500, 1500];

/** True when the gateway could not be reached: a lost request or a proxy answer while it restarts. */
export function isUnreachable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return error.code === "NETWORK" || error.code === "INVALID_RESPONSE" || [502, 503, 504].includes(error.status ?? 0);
}

/**
 * Runs `load` on mount and whenever `dependencies` change (state resets to `loading`).
 * `reload()` is stale-while-revalidate: ready data stays on screen until the new data
 * arrives, so lists do not unmount and flash a loading state after every action.
 */
export function useAsync<T>(load: () => Promise<T>, dependencies: readonly unknown[] = []): AsyncState<T> {
  const [version, setVersion] = useState(0);
  const lastVersion = useRef(version);
  const [state, setState] = useState<{ status: "loading" | "error" | "ready"; data: T | null; error: Error | null }>({
    status: "loading",
    data: null,
    error: null,
  });
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const isReload = lastVersion.current !== version;
    lastVersion.current = version;
    setState((previous) =>
      isReload && previous.status === "ready" ? previous : { status: "loading", data: null, error: null },
    );
    const run = (attemptsLeft: number) => {
      load()
        .then((data) => {
          if (active) setState({ status: "ready", data, error: null });
        })
        .catch((error: unknown) => {
          if (!active) return;
          if (attemptsLeft > 0 && isUnreachable(error)) {
            timer = setTimeout(() => run(attemptsLeft - 1), RETRY_DELAYS_MS[RETRY_DELAYS_MS.length - attemptsLeft]);
            return;
          }
          setState({ status: "error", data: null, error: error instanceof Error ? error : new Error(String(error)) });
        });
    };
    run(RETRY_DELAYS_MS.length);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [version, ...dependencies]);
  return { ...state, reload } as AsyncState<T>;
}
