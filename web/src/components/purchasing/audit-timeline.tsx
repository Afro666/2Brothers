import {
  Boxes,
  Calculator,
  ChefHat,
  ClipboardList,
  Search,
  Send,
  Share2,
  ShieldCheck,
  Tag,
  UserCheck,
  type LucideIcon,
} from "lucide-react";

import { formatDateTime } from "@/lib/format";
import type { AuditEvent, AuditKind } from "@/types";

export const KIND_META: Record<AuditKind, { label: string; icon: LucideIcon }> = {
  request: { label: "Request", icon: ChefHat },
  search: { label: "Search", icon: Search },
  offer: { label: "Offer", icon: Tag },
  simulate: { label: "Simulate", icon: Calculator },
  mandate_check: { label: "Mandate check", icon: ShieldCheck },
  approval: { label: "Approval", icon: UserCheck },
  order: { label: "Order", icon: Send },
  stock: { label: "Stock", icon: Boxes },
  forecast_share: { label: "Forecast shared", icon: Share2 },
};

export const ACTOR_LABEL: Record<AuditEvent["actor"], string> = {
  chef: "Chef",
  agent: "Agent",
  gateway: "Gateway",
  human: "Buyer",
  valio: "Valio",
  system: "System",
};

/** Every step, oldest first, each with who did it and why. */
export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  // Array.sort is stable, so steps with the same time keep the order the API recorded them in.
  const sorted = [...events].sort((a, b) => new Date(a.at).getTime() - new Date(b.at).getTime());
  if (sorted.length === 0) {
    return (
      <p className="flex items-center gap-2 text-sm text-muted-foreground">
        <ClipboardList className="size-4" aria-hidden /> No steps yet.
      </p>
    );
  }
  return (
    <ol className="relative space-y-5 border-l pl-6">
      {sorted.map((e) => {
        const meta = KIND_META[e.kind];
        const Icon = meta.icon;
        return (
          <li key={e.id} className="relative" data-kind={e.kind}>
            <span className="absolute top-0 -left-[2.3rem] flex size-7 items-center justify-center rounded-full border bg-background">
              <Icon className="size-3.5 text-muted-foreground" aria-hidden />
            </span>
            <div className="flex flex-wrap items-baseline gap-x-2 text-xs text-muted-foreground">
              <time dateTime={e.at} className="tabular-nums">
                {formatDateTime(e.at)}
              </time>
              <span>·</span>
              <span>{meta.label}</span>
              <span>·</span>
              <span>{ACTOR_LABEL[e.actor]}</span>
              {e.orderId ? (
                <>
                  <span>·</span>
                  <span>{e.orderId}</span>
                </>
              ) : null}
            </div>
            <p className="mt-0.5 text-sm font-medium">{e.summary}</p>
            <p className="text-sm text-muted-foreground">{e.reason}</p>
          </li>
        );
      })}
    </ol>
  );
}
