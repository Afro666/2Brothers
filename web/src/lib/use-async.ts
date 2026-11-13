import { useCallback, useEffect, useRef, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data: null; error: null; reload: () => void }
  | { status: "error"; data: null; error: Error; reload: () => void }
  | { status: "ready"; data: T; error: null; reload: () => void };
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
    const isReload = lastVersion.current !== version;
    lastVersion.current = version;
    setState((previous) =>
      isReload && previous.status === "ready" ? previous : { status: "loading", data: null, error: null },
    );
    load()
      .then((data) => {
        if (active) setState({ status: "ready", data, error: null });
      })
      .catch((error: unknown) => {
        if (active)
          setState({ status: "error", data: null, error: error instanceof Error ? error : new Error(String(error)) });
      });
    return () => {
      active = false;
    };
  }, [version, ...dependencies]);
  return { ...state, reload } as AsyncState<T>;
}
