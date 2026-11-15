import { ReadRefresh } from "@/components/purchasing/read-refresh";
import { formatDateTime, formatEur, formatShortfall } from "@/lib/format";
import { useLiveEvents } from "@/lib/live-events";
import { usePendingApprovals } from "@/lib/pending-approvals";
import { useAsync } from "@/lib/use-async";
import { Link } from "@tanstack/react-router";

import type { Api } from "@/api/types";
import type { ApprovalRequest, AuditEvent, DemandLine, StockItem, Supplier } from "@/types";

import { AtlasMark } from "@/components/atlas-mark";
import { isNemotron, NemotronMark } from "@/components/nemotron-mark";
import { leadOption } from "@/components/purchasing/option-compare";
import { DecisionStrip } from "@/components/purchasing/decision-strip";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { SampleData } from "@/components/purchasing/sample-data";
import { useT } from "@/lib/i18n";
import { plainCode } from "@/lib/codes";
import { inclVatOf } from "@/lib/vat";
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

/** The proposal that has waited longest. A null time (its creation step is outside the audit window) counts as oldest. */
export function oldestWaiting(pending: ApprovalRequest[]): ApprovalRequest | undefined {
  const createdAt = (approval: ApprovalRequest) => {
    const time = approval.createdAt == null ? NaN : Date.parse(approval.createdAt);
    return Number.isFinite(time) ? time : -Infinity;
  };
  return [...pending].sort((a, b) => createdAt(a) - createdAt(b))[0];
}

export function ApprovalTile({ api }: { api: Api }) {
  const t = useT();
  const state = useAsync(() => api.listApprovals(), [api], { keep: "home-approvals", scope: api });
  const { count } = usePendingApprovals();
  useLiveEvents(["proposal", "approval"], state.reload);
  return (
    <Tile
      title={t("Waiting for your approval")}
      href="/approvals"
      linkLabel={t("Review orders to approve")}
      emphasis
      footer={<DecisionStrip />}
    >
      <ReadRefresh refreshing={state.refreshing} outdated={state.outdated} reload={state.reload} />
      {state.status === "loading" && count !== null ? (
        <div>
          <p className="docket-figure text-3xl tabular-nums sm:text-[5.5rem] sm:leading-[0.8]">{count}</p>
          <p role="status" className="text-sm text-muted-foreground">{t("Loading approval details...")}</p>
        </div>
      ) : <TileState
        status={state.status}
        error={state.error}
        reload={state.reload}
        data={state.status === "ready" ? state.data : null}
        empty={false}
      >
        {(approvals: ApprovalRequest[]) => {
          const pending = approvals.filter((approval) => approval.status === "PENDING");
          const oldest = oldestWaiting(pending);
          // The card on /approvals leads with the recommended option's total (#1866): Home names the same figure.
          const lead = leadOption(oldest?.options ?? []);
          const total = lead ? lead.totalInclVat : oldest?.totalInclVat;
          const inclVat = oldest ? inclVatOf(oldest) : null;
          const byNemotron = oldest?.modelTrace?.madeBy === "model" && isNemotron(oldest.modelTrace.model);
          return pending.length === 0 ? (
            <p className="text-sm text-muted-foreground">{t("Nothing is waiting.")}</p>
          ) : (
            <div className="grid gap-x-6 gap-y-3 sm:grid-cols-[auto_1fr_auto] sm:items-end">
              <p className="docket-figure text-3xl tabular-nums sm:text-[5.5rem] sm:leading-[0.8]">{pending.length}</p>
              <div className="min-w-0 space-y-1">
                <p className="label-caps">{t("Oldest waiting")}</p>
                <p className="max-w-[60ch] text-lg font-semibold leading-snug">{oldest?.summary}</p>
                {byNemotron ? (
                  <p className="font-mono text-xs text-muted-foreground">
                    <NemotronMark />
                    {t("Proposed by the Buyer agent ({model})", { model: "Nemotron 3.5 Super VL" })}
                  </p>
                ) : null}
              </div>
              <p className="w-fit border-b-[3px] border-double border-foreground text-2xl font-bold tabular-nums sm:justify-self-end">
                {oldest
                  ? inclVat == null
                    ? t("Approve {amount}", { amount: formatEur(total ?? null) })
                    : // #1916: "incl VAT" only for the incl VAT total itself; a figure with a fee is "in all".
                      !lead && total != null && Math.abs(inclVat - total) < 0.005
                      ? t("{amount} incl VAT", { amount: formatEur(total) })
                      : t("{amount} in all", { amount: formatEur(total ?? null) })
                  : `${t(formatEur(null))} ${t("incl VAT")}`}
              </p>
            </div>
          );
        }}
      </TileState>}
    </Tile>
  );
}

export function CutoffTile({ api, now }: { api: Api; now: Date }) {
  const t = useT();
  const state = useAsync(() => api.listSuppliers(), [api], { keep: "suppliers", scope: api });
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
  const state = useAsync(() => loadKitchenStock(api, now), [api, now.toISOString()], { keep: "home-stock", scope: api });
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
                  className="flex min-h-11 w-fit items-center text-sm font-medium underline decoration-border underline-offset-4 hover:decoration-foreground"
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
  const state = useAsync(() => api.listAudit(), [api], { keep: "audit", scope: api });
  return (
    <Tile
      title={t("Latest steps")}
      href="/audit"
      linkLabel={t("Open activity log")}
      mark={<AtlasMark of="listAudit" what="The activity log is stored in MongoDB Atlas and read from it." />}
    >
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
            {/* #1978: the demo's own housekeeping steps are in the full log, not here. */}
            {events
              .filter((event) => !event.internal)
              .reverse()
              .sort((a, b) => (a.at && b.at ? Date.parse(b.at) - Date.parse(a.at) : 0))
              .slice(0, 5)
              .map((event) => (
                <li key={event.id} className="space-y-1 py-2">
                  <time className="font-mono text-xs text-muted-foreground" dateTime={event.at ?? undefined}>
                    {formatDateTime(event.at)}
                  </time>
                  <p>{t(plainCode(event.summary, t))}</p>
                </li>
              ))}
          </ul>
        )}
      </TileState>
    </Tile>
  );
}
