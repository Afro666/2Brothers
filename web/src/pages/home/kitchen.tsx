import { formatDateTime, formatEur, formatShortfall } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import { Link } from "@tanstack/react-router";

import type { Api } from "@/api/types";
import type { ApprovalRequest, AuditEvent, DemandLine, StockItem, Supplier } from "@/types";

import { ProductThumb } from "@/components/purchasing/product-thumb";
import { SampleData } from "@/components/purchasing/sample-data";
import { useT } from "@/lib/i18n";
import { nextCutoff } from "@/pages/home/cutoff";
import { HOME_STOCK_ROWS, stockToCheck } from "@/pages/home/stock-rows";
import { Tile, TileState } from "@/pages/home/tile";

function loadKitchenStock(api: Api, now: Date): Promise<{ stock: StockItem[]; demand: DemandLine[] }> {
  const from = now.toLocaleDateString("en-CA", { timeZone: "Europe/Helsinki" });
  const end = new Date(`${from}T12:00:00Z`);
  end.setUTCDate(end.getUTCDate() + 6);
  const to = end.toISOString().slice(0, 10);
  return Promise.all([api.getStock(), api.getDemand(from, to)]).then(([stock, demand]) => ({ stock, demand }));
}

export function ApprovalTile({ api }: { api: Api }) {
  const t = useT();
  const state = useAsync(() => api.listApprovals(), [api]);
  return (
    <Tile title={t("Waiting for your approval")} href="/approvals" linkLabel={t("Review orders to approve")} emphasis>
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
            <p className="text-sm text-muted-foreground">{t("Nothing is waiting.")}</p>
          ) : (
            <div className="space-y-2">
              <p className="stamp text-3xl font-semibold tabular-nums">{pending.length}</p>
              <p className="text-sm">{oldest?.summary}</p>
              <p className="text-sm font-medium tabular-nums">
                {t(formatEur(oldest?.totalInclVat ?? null))} {t("incl VAT")}
              </p>
            </div>
          );
        }}
      </TileState>
    </Tile>
  );
}

export function CutoffTile({ api, now }: { api: Api; now: Date }) {
  const t = useT();
  const state = useAsync(() => api.listSuppliers(), [api]);
  return (
    <Tile title={t("Next order cut-offs")} href="/suppliers" linkLabel={t("Review suppliers")}>
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
                    <span className="unknown-value">{t("terms not set")}</span>
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
  const t = useT();
  const state = useAsync(() => loadKitchenStock(api, now), [api, now.toISOString()]);
  return (
    <Tile title={t("Stock to check")} href="/stock" linkLabel={t("Count stock")}>
      <SampleData of="getStock" />
      <TileState
        status={state.status}
        error={state.error}
        reload={state.reload}
        data={state.status === "ready" ? state.data : null}
        empty={false}
      >
        {({ stock, demand }: { stock: StockItem[]; demand: DemandLine[] }) => {
          const rows = stockToCheck(stock, demand);
          const more = rows.length - HOME_STOCK_ROWS;
          return rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("Stock covers the next 7 days.")}</p>
          ) : (
            <>
              <ul className="divide-y text-sm">
                {rows.slice(0, HOME_STOCK_ROWS).map((row) => (
                  <li key={row.productId} className="flex items-center justify-between gap-3 py-2">
                    <span className="flex min-w-0 items-center gap-2">
                      <ProductThumb size="sm" en={row.productName} />
                      <span className="min-w-0">{row.productName}</span>
                    </span>
                    {row.kind === "short" ? (
                      <span className="shrink-0 text-right font-mono text-[13px] font-medium text-danger">
                        <span className="whitespace-nowrap">
                          {t("short by {amount}", { amount: formatShortfall(row.shortfall, row.unit) })}
                        </span>
                        {row.onOrderUnknown ? <span className="block">{t(" (on order unknown)")}</span> : null}
                      </span>
                    ) : (
                      <span className="unknown-value">{t("not counted")}</span>
                    )}
                  </li>
                ))}
              </ul>
              {more > 0 ? (
                <Link
                  to="/stock"
                  className="block w-fit text-sm font-medium underline decoration-border underline-offset-4 hover:decoration-foreground"
                >
                  {t("+{count} more", { count: more })}
                </Link>
              ) : null}
            </>
          );
        }}
      </TileState>
    </Tile>
  );
}

export function AuditTile({ api }: { api: Api }) {
  const t = useT();
  const state = useAsync(() => api.listAudit(), [api]);
  return (
    <Tile title={t("Latest steps")} href="/audit" linkLabel={t("Open activity log")}>
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
