import { useCallback, useEffect, useState } from "react";

export type AsyncState<T> =
  | { status: "loading"; data: null; error: null; reload: () => void }
  | { status: "error"; data: null; error: Error; reload: () => void }
  | { status: "ready"; data: T; error: null; reload: () => void };
export function useAsync<T>(load: () => Promise<T>, dependencies: readonly unknown[] = []): AsyncState<T> {
  const [version, setVersion] = useState(0);
  const [state, setState] = useState<{ status: "loading" | "error" | "ready"; data: T | null; error: Error | null }>({
    status: "loading",
    data: null,
    error: null,
  });
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  useEffect(() => {
    let active = true;
    setState({ status: "loading", data: null, error: null });
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
