import { formatDateTime } from "@/lib/format";
import type { AuditEvent, AuditKind } from "@/types";

export const KIND_META: Record<AuditKind, { label: string }> = {
  request: { label: "Request" },
  search: { label: "Search" },
  offer: { label: "Offer" },
  simulate: { label: "Simulate" },
  mandate_check: { label: "Mandate check" },
  approval: { label: "Approval" },
  order: { label: "Order" },
  stock: { label: "Stock" },
  forecast_share: { label: "Forecast shared" },
  settings: { label: "Settings" },
  other: { label: "Other" },
};

export const ACTOR_LABEL: Record<AuditEvent["actor"], string> = {
  chef: "Chef",
  agent: "Agent",
  gateway: "Gateway",
  human: "Buyer",
  valio: "Valio",
  system: "System",
};

const ACTOR_STYLE: Record<AuditEvent["actor"], string> = {
  chef: "bg-foreground text-background",
  human: "bg-foreground text-background",
  agent: "border border-dashed border-input text-muted-foreground",
  gateway: "border border-dashed border-input text-muted-foreground",
  system: "border border-dashed border-input text-muted-foreground",
  valio: "border border-input text-foreground",
};

/** Every step, oldest first, each with who did it and why. */
export function AuditTimeline({ events }: { events: AuditEvent[] }) {
  // Array.sort is stable, so steps with the same time keep the order the API recorded them in.
  // A step with no recorded time keeps its place in that order too.
  const sorted = [...events].sort((a, b) => (a.at && b.at ? new Date(a.at).getTime() - new Date(b.at).getTime() : 0));
  if (sorted.length === 0) {
    return <p className="text-sm text-muted-foreground">No steps yet.</p>;
  }
  return (
    <ol className="divide-y rounded-sm border bg-card">
      {sorted.map((e) => {
        const meta = KIND_META[e.kind];
        return (
          <li
            key={e.id}
            className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2 px-4 py-3 sm:grid-cols-[8.5rem_6rem_minmax(0,1fr)]"
            data-kind={e.kind}
            data-actor={e.actor}
          >
            <time dateTime={e.at ?? undefined} className="self-start font-mono text-xs leading-4 text-muted-foreground">
              {formatDateTime(e.at)}
            </time>
            <span
              className={`h-fit w-fit rounded-sm px-1.5 font-mono text-[10.5px] leading-4 font-bold tracking-wide uppercase ${ACTOR_STYLE[e.actor]}`}
            >
              {ACTOR_LABEL[e.actor]}
            </span>
            <div className="col-span-2 min-w-0 sm:col-span-1">
              <p className="label-caps">
                {meta.label}
                {e.orderId ? <span className="font-mono"> · {e.orderId}</span> : null}
              </p>
              <p className="mt-0.5 text-sm font-semibold break-words">{e.summary}</p>
              <p className="text-sm break-words text-muted-foreground">{e.reason}</p>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
