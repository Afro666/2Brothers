import { formatDateTime, formatEur, formatNumber } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import type { Api } from "@/api/types";
import type { ApprovalRequest, AuditEvent, DemandLine, StockItem, Supplier } from "@/types";

import { SampleData } from "@/components/purchasing/sample-data";
import { nextCutoff } from "@/pages/home/cutoff";
import { Tile, TileState } from "@/pages/home/tile";

function loadKitchenStock(api: Api, now: Date): Promise<{ stock: StockItem[]; demand: DemandLine[] }> {
  const from = now.toLocaleDateString("en-CA", { timeZone: "Europe/Helsinki" });
  const end = new Date(`${from}T12:00:00Z`);
  end.setUTCDate(end.getUTCDate() + 6);
  const to = end.toISOString().slice(0, 10);
  return Promise.all([api.getStock(), api.getDemand(from, to)]).then(([stock, demand]) => ({ stock, demand }));
}

export function ApprovalTile({ api }: { api: Api }) {
  const state = useAsync(() => api.listApprovals(), [api]);
  return (
    <Tile title="Waiting for your approval" href="/approvals" linkLabel="Review orders to approve" emphasis>
      <TileState
        status={state.status}
        error={state.error}
        reload={state.reload}
        data={state.status === "ready" ? state.data : null}
        empty={false}
      >
        {(approvals: ApprovalRequest[]) => {
          const pending = approvals.filter((approval) => approval.status === "PENDING");
          const oldest = [...pending].sort((a, b) => Date.parse(a.createdAt ?? "") - Date.parse(b.createdAt ?? ""))[0];
          return pending.length === 0 ? (
            <p className="text-sm text-muted-foreground">Nothing is waiting.</p>
          ) : (
            <div className="space-y-2">
              <p className="stamp text-3xl font-semibold tabular-nums">{pending.length}</p>
              <p className="text-sm">{oldest?.summary}</p>
              <p className="text-sm font-medium tabular-nums">{formatEur(oldest?.totalInclVat ?? null)} incl VAT</p>
            </div>
          );
        }}
      </TileState>
    </Tile>
  );
}

export function CutoffTile({ api, now }: { api: Api; now: Date }) {
  const state = useAsync(() => api.listSuppliers(), [api]);
  return (
    <Tile title="Next order cut-offs" href="/suppliers" linkLabel="Review suppliers">
      <SampleData of="listSuppliers" />
      <TileState
        status={state.status}
        error={state.error}
        reload={state.reload}
        data={state.status === "ready" ? state.data : null}
        empty={state.status === "ready" && state.data.length === 0}
      >
        {(suppliers: Supplier[]) => (
          <ul className="divide-y">
            {[...suppliers]
              .map((supplier) => ({ supplier, cutoff: nextCutoff(supplier, now) }))
              .sort((a, b) => (a.cutoff?.getTime() ?? Infinity) - (b.cutoff?.getTime() ?? Infinity))
              .map(({ supplier, cutoff }) => (
                <li key={supplier.id} className="flex items-start justify-between gap-3 py-2 text-sm">
                  <span className="min-w-0 font-medium">{supplier.name}</span>
                  {cutoff ? (
                    <time
                      dateTime={cutoff.toISOString()}
                      className={`text-right font-mono text-[13px] ${
                        cutoff.getTime() - now.getTime() < 3 * 60 * 60 * 1000
                          ? "font-medium text-danger"
                          : "text-muted-foreground"
                      }`}
                    >
                      {formatDateTime(cutoff.toISOString())}
                    </time>
                  ) : (
                    <span className="unknown-value">terms not set</span>
                  )}
                </li>
              ))}
          </ul>
        )}
      </TileState>
    </Tile>
  );
}

export function StockTile({ api, now }: { api: Api; now: Date }) {
  const state = useAsync(() => loadKitchenStock(api, now), [api, now.toISOString()]);
  return (
    <Tile title="Stock to check" href="/stock" linkLabel="Count stock">
      <SampleData of="getStock" />
      <TileState
        status={state.status}
        error={state.error}
        reload={state.reload}
        data={state.status === "ready" ? state.data : null}
        empty={false}
      >
        {({ stock, demand }: { stock: StockItem[]; demand: DemandLine[] }) => {
          const needed = new Map<string, number>();
          for (const line of demand) needed.set(line.productId, (needed.get(line.productId) ?? 0) + line.need);
          const unknown = stock.filter((item) => item.onHand === null);
          const countedIds = new Set(stock.map((item) => item.productId));
          const uncounted = demand
            .filter((line) => !countedIds.has(line.productId))
            .filter(
              (line, index, lines) => lines.findIndex((candidate) => candidate.productId === line.productId) === index,
            );
          const short = stock.filter(
            (item): item is StockItem & { onHand: number } =>
              // On order unknown: the count alone decides, and the row says so.
              item.onHand !== null && (needed.get(item.productId) ?? 0) > item.onHand + (item.onOrder ?? 0),
          );
          return unknown.length + uncounted.length + short.length === 0 ? (
            <p className="text-sm text-muted-foreground">Stock covers the next 7 days.</p>
          ) : (
            <ul className="divide-y text-sm">
              {unknown.map((item) => (
                <li key={item.productId} className="flex items-start justify-between gap-3 py-2">
                  <span className="min-w-0">{item.productName}</span>
                  <span className="unknown-value">not counted</span>
                </li>
              ))}
              {uncounted.map((item) => (
                <li key={item.productId} className="flex items-start justify-between gap-3 py-2">
                  <span className="min-w-0">{item.productName}</span>
                  <span className="unknown-value">not counted</span>
                </li>
              ))}
              {short.map((item) => (
                <li key={item.productId} className="flex items-start justify-between gap-3 py-2">
                  <span className="min-w-0">{item.productName}</span>
                  <span className="text-right font-mono text-[13px] font-medium text-danger">
                    short by {formatNumber((needed.get(item.productId) ?? 0) - item.onHand - (item.onOrder ?? 0))}{" "}
                    {item.unit}
                    {item.onOrder === null ? " (on order unknown)" : ""}
                  </span>
                </li>
              ))}
            </ul>
          );
        }}
      </TileState>
    </Tile>
  );
}

export function AuditTile({ api }: { api: Api }) {
  const state = useAsync(() => api.listAudit(), [api]);
  return (
    <Tile title="Latest steps" href="/audit" linkLabel="Open activity log">
      <TileState
        status={state.status}
        error={state.error}
        reload={state.reload}
        data={state.status === "ready" ? state.data : null}
        empty={state.status === "ready" && state.data.length === 0}
      >
        {(events: AuditEvent[]) => (
          <ul className="divide-y text-sm">
            {/* Newest first; a step with no recorded time keeps the order the API recorded it in. */}
            {[...events]
              .reverse()
              .sort((a, b) => (a.at && b.at ? Date.parse(b.at) - Date.parse(a.at) : 0))
              .slice(0, 5)
              .map((event) => (
                <li key={event.id} className="space-y-1 py-2">
                  <time className="font-mono text-xs text-muted-foreground" dateTime={event.at ?? undefined}>
                    {formatDateTime(event.at)}
                  </time>
                  <p>{event.summary}</p>
                </li>
              ))}
          </ul>
        )}
      </TileState>
    </Tile>
  );
}
