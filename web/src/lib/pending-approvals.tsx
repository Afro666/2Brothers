import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

import { useApi } from "@/api";
import { useLiveConnected, useLiveEvents } from "@/lib/live-events";

interface PendingApprovals {
  /** How many approvals wait for a person. null = not known (loading or the gateway failed): show no badge. */
  count: number | null;
  /** Ask again, e.g. right after an approve or reject. */
  refresh: () => void;
}

const PendingApprovalsContext = createContext<PendingApprovals>({ count: null, refresh: () => {} });

/**
 * One source for the "waiting for you" count: the menu and the tabs read it, and the
 * Approvals page calls `refresh()` after a decision. Without it the shell would fetch
 * the approvals again on every page.
 */
/** How often the count is asked again, so proposals the Buyer agent makes while the app is open show up. */
export const PENDING_APPROVALS_REFRESH_MS = 30_000;

export function PendingApprovalsProvider({
  children,
  intervalMs = PENDING_APPROVALS_REFRESH_MS,
}: {
  children: ReactNode;
  intervalMs?: number;
}) {
  const api = useApi();
  const [count, setCount] = useState<number | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let active = true;
    (api.countPendingApprovals
      ? api.countPendingApprovals()
      : api.listApprovals().then(
          (approvals) => approvals.filter((approval) => approval.status === "PENDING").length,
        ))
      .then((count) => {
        if (active) setCount(count);
      })
      .catch(() => {
        // Unknown is not zero: no badge until the next successful load.
        if (active) setCount(null);
      });
    return () => {
      active = false;
    };
  }, [api, version]);
  const refresh = useCallback(() => setVersion((value) => value + 1), []);
  useLiveEvents(["proposal", "approval"], refresh);
  const liveConnected = useLiveConnected();
  // The stream sends only new events: a proposal or approval made while it was down is asked
  // for once when it connects again.
  const wasConnected = useRef(liveConnected);
  useEffect(() => {
    if (liveConnected && !wasConnected.current) refresh();
    wasConnected.current = liveConnected;
  }, [liveConnected, refresh]);
  // The connected event stream already refreshes the count; without it, ask every 30 s while the
  // tab is seen, and at once when it is seen again.
  useEffect(() => {
    if (liveConnected) return;
    const whenSeen = () => {
      if (!document.hidden) refresh();
    };
    const timer = setInterval(whenSeen, intervalMs);
    document.addEventListener("visibilitychange", whenSeen);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", whenSeen);
    };
  }, [refresh, intervalMs, liveConnected]);
  const value = useMemo(() => ({ count, refresh }), [count, refresh]);
  return <PendingApprovalsContext.Provider value={value}>{children}</PendingApprovalsContext.Provider>;
}

export function usePendingApprovals(): PendingApprovals {
  return useContext(PendingApprovalsContext);
}
