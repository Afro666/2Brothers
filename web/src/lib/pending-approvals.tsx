import { createContext, type ReactNode, useCallback, useContext, useEffect, useMemo, useState } from "react";

import { useApi } from "@/api";

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
    api
      .listApprovals()
      .then((approvals) => {
        if (active) setCount(approvals.filter((approval) => approval.status === "PENDING").length);
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
  useEffect(() => {
    const timer = setInterval(refresh, intervalMs);
    return () => clearInterval(timer);
  }, [refresh, intervalMs]);
  const value = useMemo(() => ({ count, refresh }), [count, refresh]);
  return <PendingApprovalsContext.Provider value={value}>{children}</PendingApprovalsContext.Provider>;
}

export function usePendingApprovals(): PendingApprovals {
  return useContext(PendingApprovalsContext);
}
