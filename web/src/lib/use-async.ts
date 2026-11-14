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

/** The last answer of a read-only view, by key: shown at once on the next visit while the load runs again. */
const kept = new Map<string, unknown>();
/** Counts the drops, so a load that began before a drop does not put its older answer back. */
let drops = 0;
/** The newest load per key: an older load that answers late neither replaces nor forgets its answer. */
const newest = new Map<string, number>();

/**
 * Forgets every kept answer. Called before every write, on every live event and on sign-out
 * (api/http.ts, lib/live-events.tsx), so nothing older than a change is shown as current.
 */
export function dropKeptAnswers(): void {
  kept.clear();
  drops += 1;
}

/**
 * Runs `load` on mount and whenever `dependencies` change (state resets to `loading`).
 * `reload()` is stale-while-revalidate: ready data stays on screen until the new data
 * arrives, so lists do not unmount and flash a loading state after every action.
 *
 * `keep` names a read-only view: its last answer is shown at once on the next visit and the load
 * still runs. Never give a key to a view whose total a person approves or whose numbers a person
 * edits. A failed load forgets the kept answer and shows the error: an old number is not shown
 * as current after a failure.
 */
export function useAsync<T>(
  load: () => Promise<T>,
  dependencies: readonly unknown[] = [],
  options: { keep?: string } = {},
): AsyncState<T> {
  const { keep } = options;
  const [version, setVersion] = useState(0);
  const lastVersion = useRef(version);
  const [state, setState] = useState<{ status: "loading" | "error" | "ready"; data: T | null; error: Error | null }>(
    () =>
      keep !== undefined && kept.has(keep)
        ? { status: "ready", data: kept.get(keep) as T, error: null }
        : { status: "loading", data: null, error: null },
  );
  const reload = useCallback(() => setVersion((value) => value + 1), []);
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const isReload = lastVersion.current !== version;
    lastVersion.current = version;
    setState((previous) => {
      if (isReload && previous.status === "ready") return previous;
      if (keep !== undefined && kept.has(keep)) return { status: "ready", data: kept.get(keep) as T, error: null };
      return { status: "loading", data: null, error: null };
    });
    const dropsAtStart = drops;
    const mine = keep === undefined ? 0 : (newest.get(keep) ?? 0) + 1;
    if (keep !== undefined) newest.set(keep, mine);
    const current = () => keep !== undefined && drops === dropsAtStart && newest.get(keep) === mine;
    const run = (attemptsLeft: number) => {
      load()
        .then((data) => {
          if (keep !== undefined && current()) kept.set(keep, data);
          if (active) setState({ status: "ready", data, error: null });
        })
        .catch((error: unknown) => {
          if (!active) return;
          if (attemptsLeft > 0 && isUnreachable(error)) {
            timer = setTimeout(() => run(attemptsLeft - 1), RETRY_DELAYS_MS[RETRY_DELAYS_MS.length - attemptsLeft]);
            return;
          }
          if (keep !== undefined && current()) kept.delete(keep);
          setState({ status: "error", data: null, error: error instanceof Error ? error : new Error(String(error)) });
        });
    };
    run(RETRY_DELAYS_MS.length);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [version, keep, ...dependencies]);
  return { ...state, reload } as AsyncState<T>;
}
