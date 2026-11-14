import { useId, useState } from "react";

import { formatDateTime } from "@/lib/format";
import { CODE_LABELS, plainCode } from "@/lib/codes";
import { useT } from "@/lib/i18n";
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
  refused: { label: "Refused" },
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

export type AuditOutcome = "waiting for approval" | "approved" | "rejected" | "refused" | "order placed" | "none";

export interface AuditStepGroup {
  id: string;
  title: string;
  titleEvent: AuditEvent | null;
  outcome: AuditOutcome;
  decidedBy: string | null;
  total: string | null;
  at: string | null;
  rows: AuditEvent[];
  events: AuditEvent[];
}

function timestamp(event: { at: string | null }): number | null {
  if (!event.at) return null;
  const value = new Date(event.at).getTime();
  return Number.isFinite(value) ? value : null;
}

function oldestFirst(events: AuditEvent[]): AuditEvent[] {
  return events
    .map((event, index) => ({ event, index }))
    .sort((a, b) => {
      const left = timestamp(a.event);
      const right = timestamp(b.event);
      return left != null && right != null ? left - right || a.index - b.index : a.index - b.index;
    })
    .map(({ event }) => event);
}

const TOOL_CALLS = [
  ["Buyer is searching the catalog", "Buyer searched the catalog"],
  ["Buyer is asking for an offer", "Buyer got the offer"],
  ["Buyer is simulating the order", "Buyer simulated the order"],
  ["Buyer is asking for approval", "Buyer asked for approval"],
  ["Buyer is placing the order", "Buyer placed the order"],
  ["Buyer is checking the order status", "Buyer checked the order status"],
] as const;

function toolCall(event: AuditEvent): { key: string; started: boolean } | null {
  for (const [started, finished] of TOOL_CALLS) {
    if (event.summary === started) return { key: `${event.kind}:${started}`, started: true };
    if (event.summary === finished || event.summary === `${finished}: it failed`) {
      return { key: `${event.kind}:${started}`, started: false };
    }
  }
  if (event.summary.startsWith("Buyer called ")) {
    return { key: `unknown:${event.summary.slice("Buyer called ".length)}`, started: true };
  }
  const unknown = /^(.*?) (?:finished|failed)$/.exec(event.summary);
  return unknown ? { key: `unknown:${unknown[1]}`, started: false } : null;
}

function collapseToolCalls(events: AuditEvent[]): AuditEvent[] {
  const rows: AuditEvent[] = [];
  const pending = new Map<string, number[]>();
  for (const event of events) {
    const call = toolCall(event);
    if (!call) {
      rows.push(event);
      continue;
    }
    const waiting = pending.get(call.key) ?? [];
    if (call.started) {
      waiting.push(rows.length);
      pending.set(call.key, waiting);
      rows.push(event);
      continue;
    }
    const startedIndex = waiting.shift();
    if (startedIndex == null) {
      rows.push(event);
      continue;
    }
    const started = rows[startedIndex];
    rows[startedIndex] = {
      ...finishedWithStartedDetails(started, event),
    };
  }
  return rows;
}

function finishedWithStartedDetails(started: AuditEvent, finished: AuditEvent): AuditEvent {
  const details = [...new Set([started.details, finished.details].filter((value): value is string => Boolean(value)))];
  return {
    ...finished,
    at: finished.at ?? started.at,
    orderId: finished.orderId ?? started.orderId,
    groupIds: [...new Set([...(started.groupIds ?? []), ...(finished.groupIds ?? [])])],
    ...(details.length ? { details: details.join("\n") } : {}),
  };
}

function outcomeOf(events: AuditEvent[]): { outcome: AuditOutcome; event: AuditEvent | null } {
  const summaries = events.map((event) => event.summary.toLowerCase());
  const placed = events.find((event, index) => event.kind === "order" && summaries[index].includes("placed"));
  if (placed) return { outcome: "order placed", event: placed };
  const rejected = events.find((_, index) => summaries[index].includes("reject") || summaries[index].includes("declined"));
  if (rejected) return { outcome: "rejected", event: rejected };
  const refused = events.find((event) => event.kind === "refused");
  if (refused) return { outcome: "refused", event: refused };
  const approved = events.find(
    (event, index) => (event.actor === "chef" || event.actor === "human") && summaries[index].includes("approved"),
  );
  if (approved) return { outcome: "approved", event: approved };
  const waiting = events.find(
    (event, index) =>
      !summaries[index].includes("it failed") &&
      (event.summary === "Approval requested" ||
        event.summary === "Buyer asked for approval" ||
        summaries[index].includes("needs approval") ||
        summaries[index].includes("waiting for approval")),
  );
  return waiting ? { outcome: "waiting for approval", event: waiting } : { outcome: "none", event: null };
}

function expectedTotal(events: AuditEvent[]): string | null {
  for (let index = events.length - 1; index >= 0; index -= 1) {
    const match = /(?:^|;\s*)expected_total:\s*([^;]+)/m.exec(events[index].details ?? "");
    if (!match) continue;
    const value = match[1].trim();
    try {
      const parsed: unknown = JSON.parse(value);
      return typeof parsed === "string" ? parsed : value;
    } catch {
      return value;
    }
  }
  return null;
}

/** The words the person asked for, from `Asked: "20 L oat drink for Monday" (...)`; else the first sentence. */
export function shortTitle(summary: string): string {
  const asked = /^Asked: "([^"]+)"/.exec(summary)?.[1];
  if (asked) return asked;
  const first = summary.split(/(?<=\.)\s/)[0];
  return first.length <= 120 ? first : `${first.slice(0, 117)}...`;
}

/** `at` is the time of the step the outcome chip names; `latest` (the newest step) only orders the groups. */
function makeGroup(events: AuditEvent[], index: number): AuditStepGroup & { index: number; latest: string | null } {
  const titleEvent = events.find((event) => event.summary === "Decision summary") ?? null;
  const rows = oldestFirst(collapseToolCalls(events).filter((event) => event.id !== titleEvent?.id));
  const { outcome, event: outcomeEvent } = outcomeOf(events);
  let latest: string | null = null;
  for (const event of events) if (timestamp(event) != null) latest = event.at;
  const at = outcomeEvent && timestamp(outcomeEvent) != null ? outcomeEvent.at : latest;
  const decider = [...events].reverse().find(
    (event) =>
      (event.actor === "chef" || event.actor === "human") &&
      event.actorName &&
      /approved|reject|placed/i.test(event.summary),
  );
  return {
    id: events[0].id,
    title: titleEvent?.reason ? shortTitle(titleEvent.reason) : events[0].summary,
    titleEvent,
    outcome,
    decidedBy: decider?.actorName ?? null,
    total: expectedTotal(events),
    at,
    rows,
    events,
    index,
    latest,
  };
}

function translatedReason(event: AuditEvent, t: ReturnType<typeof useT>): string {
  // The log records what happened: a code's plain name, not the approval card's advice ("It cannot be approved").
  if (Object.hasOwn(CODE_LABELS, event.reason)) return plainCode(event.reason, t);
  if (event.actor !== "agent") return event.reason;
  const productsForDate = /^(\d+) products? for (.+)$/.exec(event.reason);
  if (productsForDate) {
    const count = productsForDate[1];
    const date = productsForDate[2];
    return count === "1"
      ? t("{count} product for {date}", { count, date })
      : t("{count} products for {date}", { count, date });
  }
  const products = /^(\d+) products?$/.exec(event.reason);
  if (products) {
    const count = products[1];
    return count === "1" ? t("{count} product", { count }) : t("{count} products", { count });
  }
  const date = /^For (.+)$/.exec(event.reason);
  if (date) return t("For {date}", { date: date[1] });
  const query = /^Looking for “([^”]+)”$/.exec(event.reason);
  return query ? t("Looking for “{query}”", { query: query[1] }) : event.reason;
}

/** Groups connected ids transitively, while an id-less event always remains its own request. */
export function groupSteps(events: AuditEvent[]): AuditStepGroup[] {
  const sorted = oldestFirst(events);
  const parents = sorted.map((_, index) => index);
  function root(index: number): number {
    let current = index;
    while (parents[current] !== current) current = parents[current];
    while (parents[index] !== index) {
      const next = parents[index];
      parents[index] = current;
      index = next;
    }
    return current;
  }
  function join(left: number, right: number) {
    const leftRoot = root(left);
    const rightRoot = root(right);
    if (leftRoot !== rightRoot) parents[rightRoot] = leftRoot;
  }

  const idOwner = new Map<string, number>();
  sorted.forEach((event, index) => {
    for (const id of new Set((event.groupIds ?? []).filter(Boolean))) {
      const owner = idOwner.get(id);
      if (owner == null) idOwner.set(id, index);
      else join(index, owner);
    }
  });
  const connected = new Map<number, AuditEvent[]>();
  sorted.forEach((event, index) => {
    const key = root(index);
    const list = connected.get(key);
    if (list) list.push(event);
    else connected.set(key, [event]);
  });
  const groups = [...connected.values()].map((events, index) => makeGroup(events, index));
  const known = groups
    .filter((group) => timestamp({ at: group.latest }) != null)
    .sort((a, b) => (timestamp({ at: b.latest }) ?? 0) - (timestamp({ at: a.latest }) ?? 0) || a.index - b.index);
  let nextKnown = 0;
  return groups
    .map((group) => (timestamp({ at: group.latest }) == null ? group : known[nextKnown++]))
    .map(({ index: _index, latest: _latest, ...group }) => group);
}

function AuditStepRow({
  event,
  showOrder = false,
  groupTitle,
}: {
  event: AuditEvent;
  showOrder?: boolean;
  groupTitle?: string;
}) {
  const t = useT();
  // The gateway may send kinds or actors this app does not know yet: show the raw value.
  const kindLabel = KIND_META[event.kind]?.label ? t(KIND_META[event.kind].label) : event.kind;
  const actorLabel = ACTOR_LABEL[event.actor] ? t(ACTOR_LABEL[event.actor]) : event.actor;
  const actorStyle = ACTOR_STYLE[event.actor] ?? ACTOR_STYLE.system;
  const person = event.actor === "chef" || event.actor === "human";
  const summary = t(plainCode(event.summary, t));
  return (
    <li
      className={`grid grid-cols-[minmax(0,1fr)_auto] gap-x-4 gap-y-2 px-4 py-3 sm:grid-cols-[8.5rem_6rem_minmax(0,1fr)] ${person ? "bg-muted/30" : ""}`}
      data-kind={event.kind}
      data-actor={event.actor}
    >
      <time dateTime={event.at ?? undefined} className="self-start font-mono text-xs leading-4 text-muted-foreground">
        {formatDateTime(event.at)}
      </time>
      <span
        className={`h-fit w-fit rounded-sm px-1.5 font-mono text-[10.5px] leading-4 font-bold tracking-wide uppercase ${actorStyle}`}
      >
        {actorLabel}
      </span>
      <div className="col-span-2 min-w-0 sm:col-span-1">
        <p className="label-caps">
          {event.kind === "other" ? null : kindLabel}
          {showOrder && event.orderId ? (
            <span className="font-mono">{event.kind === "other" ? null : " · "}{event.orderId}</span>
          ) : null}
        </p>
        {event.summary !== groupTitle ? <p className="mt-0.5 text-sm font-semibold break-words">{summary}</p> : null}
        {event.actorName ? (
          <p className="text-sm break-all" data-actor-name>
            {t("By {name}", { name: event.actorName })}
          </p>
        ) : null}
        {event.reason && event.reason !== event.details ? (
          <p className="text-sm break-words text-muted-foreground">{translatedReason(event, t)}</p>
        ) : null}
        {event.details ? (
          <details className="mt-1 text-xs text-muted-foreground">
            <summary className="w-fit cursor-pointer">{t("Details")}</summary>
            <pre className="mt-1 font-mono break-words whitespace-pre-wrap">{event.details}</pre>
          </details>
        ) : null}
      </div>
    </li>
  );
}

function outcomeLabel(group: AuditStepGroup, t: ReturnType<typeof useT>): string | null {
  if (group.outcome === "waiting for approval") return t("Waiting for approval");
  if (group.outcome === "approved") return group.decidedBy ? t("Approved by {name}", { name: group.decidedBy }) : t("Approved");
  if (group.outcome === "rejected") return t("Rejected");
  if (group.outcome === "refused") return t("Refused");
  if (group.outcome === "order placed") return t("Order placed");
  return null;
}

function AuditGroupCard({ group }: { group: AuditStepGroup }) {
  const t = useT();
  const [expanded, setExpanded] = useState(false);
  const headingId = useId();
  const lastId = group.rows.at(-1)?.id;
  const visible =
    expanded || group.rows.length <= 4
      ? group.rows
      : group.rows.filter((event) => event.actor === "chef" || event.actor === "human" || event.id === lastId);
  const outcome = outcomeLabel(group, t);
  return (
    <section className="overflow-hidden rounded-sm border bg-card" aria-labelledby={headingId}>
      <header className="flex flex-wrap items-start justify-between gap-x-4 gap-y-2 border-b bg-muted/20 px-4 py-3">
        <div className="min-w-0 flex-1">
          <h2 id={headingId} className="text-base font-semibold break-words">
            {t(plainCode(group.title, t))}
          </h2>
          {group.titleEvent && (group.titleEvent.reason || group.titleEvent.details) ? (
            <details className="mt-1 text-xs text-muted-foreground">
              <summary className="w-fit cursor-pointer">{t("Details")}</summary>
              {group.titleEvent.reason ? (
                <p className="mt-1 text-sm break-words whitespace-pre-wrap">{group.titleEvent.reason}</p>
              ) : null}
              {group.titleEvent.details ? (
                <pre className="mt-1 font-mono break-words whitespace-pre-wrap">{group.titleEvent.details}</pre>
              ) : null}
            </details>
          ) : null}
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {outcome ? (
            <span className="rounded-sm border bg-background px-2 py-1 text-xs font-semibold" aria-label={outcome}>
              {outcome}
            </span>
          ) : null}
          <time dateTime={group.at ?? undefined} className="py-1 font-mono text-xs text-muted-foreground">
            {formatDateTime(group.at)}
          </time>
        </div>
      </header>
      {visible.length ? (
        <ol className="divide-y">
          {visible.map((event) => (
            <AuditStepRow key={event.id} event={event} groupTitle={group.title} />
          ))}
        </ol>
      ) : null}
      {group.rows.length > 4 ? (
        <ButtonShowAll expanded={expanded} count={group.rows.length} onClick={() => setExpanded((value) => !value)} />
      ) : null}
    </section>
  );
}

function ButtonShowAll({ expanded, count, onClick }: { expanded: boolean; count: number; onClick: () => void }) {
  const t = useT();
  return (
    <button
      type="button"
      className="w-full border-t px-4 py-2 text-sm font-medium underline-offset-4 hover:underline"
      onClick={onClick}
      aria-label={expanded ? t("Show fewer steps") : t("Show all {count} steps", { count })}
    >
      {expanded ? t("Show fewer steps") : t("Show all {count} steps", { count })}
    </button>
  );
}

/** Every step, oldest first, each with who did it and why. Request groups are optional for the Activity log. */
export function AuditTimeline({ events, groups }: { events: AuditEvent[]; groups?: AuditStepGroup[] }) {
  const t = useT();
  if (groups) {
    if (groups.length === 0) return <p className="text-sm text-muted-foreground">{t("No steps yet.")}</p>;
    return (
      <div className="space-y-4">
        {groups.map((group) => (
          <AuditGroupCard key={group.id} group={group} />
        ))}
      </div>
    );
  }
  const sorted = oldestFirst(events);
  if (sorted.length === 0) {
    return <p className="text-sm text-muted-foreground">{t("No steps yet.")}</p>;
  }
  return (
    <ol className="divide-y rounded-sm border bg-card">
      {sorted.map((event) => (
        <AuditStepRow key={event.id} event={event} showOrder />
      ))}
    </ol>
  );
}
