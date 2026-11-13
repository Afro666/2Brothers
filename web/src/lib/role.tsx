import { useNavigate, useRouterState } from "@tanstack/react-router";
import { createContext, type ReactNode, useContext, useState } from "react";

import type { AuditEvent } from "@/types";

export type Role = "chef" | "buyer" | "valio_planner";
export type Side = "kitchen" | "valio";

export const ROLE_LABELS: Record<Role, string> = {
  chef: "Chef",
  buyer: "Buyer",
  valio_planner: "Valio planner",
};

export function roleSide(role: Role): Side {
  return role === "valio_planner" ? "valio" : "kitchen";
}

/** The actor a decision by this role is recorded as in the audit log. */
export function auditActorForRole(role: Role): AuditEvent["actor"] {
  return role === "chef" ? "chef" : "human";
}

const VALIO_PATHS = ["/", "/demand", "/audit", "/kit"];

/** Whether a route exists on a side; switching sides leaves a route that does not. */
export function pathExistsOnSide(pathname: string, side: Side): boolean {
  return side === "valio" ? VALIO_PATHS.includes(pathname) : pathname !== "/demand";
}

interface RoleContextValue {
  role: Role;
  side: Side;
  setRole: (role: Role) => void;
}

const RoleContext = createContext<RoleContextValue | null>(null);
const STORAGE_KEY = "purchasing-role";

function storedRole(): Role {
  try {
    const stored = localStorage.getItem(STORAGE_KEY);
    if (stored === "chef" || stored === "buyer" || stored === "valio_planner") return stored;
  } catch {
    // Storage can be blocked; the picker still works for this visit.
  }
  return "buyer";
}

/** No login: the viewer picks who they are. Must sit inside the router. */
export function RoleProvider({ children }: { children: ReactNode }) {
  const [role, setCurrent] = useState<Role>(storedRole);
  const navigate = useNavigate();
  const pathname = useRouterState({ select: (state) => state.location.pathname });

  function setRole(next: Role) {
    setCurrent(next);
    try {
      localStorage.setItem(STORAGE_KEY, next);
    } catch {
      // Not remembered next visit; nothing else depends on it.
    }
    if (!pathExistsOnSide(pathname, roleSide(next))) void navigate({ to: "/" });
  }

  return <RoleContext.Provider value={{ role, side: roleSide(role), setRole }}>{children}</RoleContext.Provider>;
}

export function useRole(): RoleContextValue {
  const value = useContext(RoleContext);
  if (!value) throw new Error("useRole must be used within RoleProvider");
  return value;
}
