import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "@/api/types";

export type AsyncState<T> =
  | { status: "loading"; data: null; error: null; reload: () => Promise<void>; refreshing: boolean }
  | { status: "error"; data: null; error: Error; reload: () => Promise<void>; refreshing: boolean }
  | { status: "ready"; data: T; error: null; reload: () => Promise<void>; refreshing: boolean };
/** Retry delays for a load whose request may have been lost in the venue wifi or a deploy restart. */
const RETRY_DELAYS_MS = [500, 1500];

/** True when the gateway could not be reached: a lost request or a proxy answer while it restarts. */
export function isUnreachable(error: unknown): boolean {
  if (!(error instanceof ApiError)) return false;
  return error.code === "NETWORK" || error.code === "INVALID_RESPONSE" || [502, 503, 504].includes(error.status ?? 0);
}

/** The last answer of a read-only view, by key: shown at once on the next visit while the load runs again. */
const KEEP_MS = 60_000;
const MAX_KEPT = 64;
const kept = new Map<string, { data: unknown; until: number }>();
const scopes = new WeakMap<object, number>();
let scopeId = 0;
function scopedKey(key: string | undefined, scope?: object): string | undefined {
  if (key === undefined) return undefined;
  if (!scope) return `default:${key}`;
  if (!scopes.has(scope)) scopes.set(scope, ++scopeId);
  return `${scopes.get(scope)}:${key}`;
}
function keptAnswer(key: string | undefined) {
  if (key === undefined) return undefined;
  const answer = kept.get(key);
  if (answer && answer.until > Date.now()) return answer;
  kept.delete(key);
  return undefined;
}
/** Also partitions in-flight HTTP reads across session changes and mutations. */
export function readCacheRevision(): number { return drops; }
/** Counts the drops, so a load that began before a drop does not put its older answer back. */
let drops = 0;
let requestId = 0;
/** The newest load per key: an older load that answers late neither replaces nor forgets its answer. */
const newest = new Map<string, number>();

/**
 * Forgets every kept answer. Called before every write, on every live event and on sign-out
 * (api/http.ts, lib/live-events.tsx), so nothing older than a change is shown as current.
 */
export function dropKeptAnswers(): void {
  kept.clear();
  newest.clear();
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
  options: { keep?: string; scope?: object } = {},
): AsyncState<T> {
  const keep = scopedKey(options.keep, options.scope);
  const cached = keptAnswer(keep);
  const [version, setVersion] = useState(0);
  const lastVersion = useRef(version);
  const requested = useRef(0);
  /** Each reload's promise and the version that answers it. */
  const reloadWaiters = useRef<{ version: number; resolve: () => void }[]>([]);
  const [state, setState] = useState<{ status: "loading" | "error" | "ready"; data: T | null; error: Error | null; refreshing: boolean; key?: string }>(
    () =>
      cached
        ? { status: "ready", data: cached.data as T, error: null, refreshing: true, key: keep }
        : { status: "loading", data: null, error: null, refreshing: false, key: keep },
  );
  const reload = useCallback(
    () =>
      new Promise<void>((resolve) => {
        requested.current += 1;
        reloadWaiters.current.push({ version: requested.current, resolve });
        setVersion(requested.current);
      }),
    [],
  );
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const isReload = lastVersion.current !== version;
    lastVersion.current = version;
    setState((previous) => {
      if (isReload && previous.status === "ready" && previous.key === keep) return previous;
      const answer = keptAnswer(keep);
      if (answer) return { status: "ready", data: answer.data as T, error: null, refreshing: true, key: keep };
      return { status: "loading", data: null, error: null, refreshing: false, key: keep };
    });
    let dropsAtStart = drops;
    let mine = 0;
    const current = () => keep !== undefined && drops === dropsAtStart && newest.get(keep) === mine;
    // Only the reloads this load answers: a load that began earlier and lands late must not end a newer one.
    const finishReload = () => {
      if (!active) return;
      const done = reloadWaiters.current.filter((waiter) => waiter.version <= version);
      reloadWaiters.current = reloadWaiters.current.filter((waiter) => waiter.version > version);
      done.forEach((waiter) => waiter.resolve());
    };
    const run = (attemptsLeft: number) => {
      if (!active) return;
      dropsAtStart = drops;
      mine = ++requestId;
      if (keep !== undefined) {
        newest.delete(keep);
        if (newest.size >= MAX_KEPT) newest.delete(newest.keys().next().value!);
        newest.set(keep, mine);
      }
      const revision = dropsAtStart;
      load()
        .then((data) => {
          // An invalidated display read must ask again, not present a pre-change answer as current.
          if (active && keep !== undefined && revision !== drops) {
            run(RETRY_DELAYS_MS.length);
            return;
          }
          if (keep !== undefined && current()) {
            kept.delete(keep);
            if (kept.size >= MAX_KEPT) kept.delete(kept.keys().next().value!);
            kept.set(keep, { data, until: Date.now() + KEEP_MS });
          }
          if (active) {
            setState({ status: "ready", data, error: null, refreshing: false, key: keep });
            finishReload();
          }
        })
        .catch((error: unknown) => {
          if (!active) return;
          if (keep !== undefined && revision !== drops) {
            run(RETRY_DELAYS_MS.length);
            return;
          }
          if (attemptsLeft > 0 && isUnreachable(error)) {
            timer = setTimeout(() => run(attemptsLeft - 1), RETRY_DELAYS_MS[RETRY_DELAYS_MS.length - attemptsLeft]);
            return;
          }
          if (keep !== undefined && current()) kept.delete(keep);
          setState({ status: "error", data: null, error: error instanceof Error ? error : new Error(String(error)), refreshing: false, key: keep });
          finishReload();
        });
    };
    run(RETRY_DELAYS_MS.length);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [version, keep, ...dependencies]);
  // A changed week/filter/scope must never paint the previous key's data, even before effects run.
  if (keep !== undefined && state.key !== keep) {
    return (cached
      ? { status: "ready", data: cached.data as T, error: null, refreshing: true, reload }
      : { status: "loading", data: null, error: null, refreshing: false, reload }) as AsyncState<T>;
  }
  return { ...state, reload } as AsyncState<T>;
}
