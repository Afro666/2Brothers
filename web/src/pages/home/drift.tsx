import { ApiError } from "@/api/types";
import type { Api } from "@/api/types";
import { formatDate } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import type { DriftReport, DriftWarning } from "@/types";

import { SampleData } from "@/components/purchasing/sample-data";
import { Tile, TileState } from "@/pages/home/tile";

const KIND_LABEL: Record<DriftWarning["kind"], string> = {
  portion_creep: "Portions creeping",
  cost_creep: "Price creeping",
};

/**
 * Until the gateway serves the drift route, or while drift is unavailable
 * (503 DRIFT_UNAVAILABLE), the tile is not shown at all.
 */
async function loadDrift(
  load: () => Promise<DriftReport>,
): Promise<DriftReport | null> {
  try {
    return await load();
  } catch (error) {
    if (
      error instanceof ApiError &&
      (error.code === "NOT_SERVED" || error.code === "DRIFT_UNAVAILABLE")
    ) {
      return null;
    }
    throw error;
  }
}

function DriftList({
  warnings,
  showKitchen,
}: {
  warnings: DriftWarning[];
  showKitchen: boolean;
}) {
  return (
    <ul className="space-y-3 text-sm">
      {warnings.map((warning) => (
        <li
          key={`${warning.kitchenId ?? ""}-${warning.productId}-${warning.kind}`}
          className="space-y-1"
        >
          <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <span className="min-w-0 font-medium">
              {warning.productName ?? warning.productId}
              {showKitchen && warning.kitchenName ? (
                <span className="font-normal text-muted-foreground">
                  {" "}
                  · {warning.kitchenName}
                </span>
              ) : null}
            </span>
            <span className="tabular-nums text-destructive">
              {KIND_LABEL[warning.kind]} +{Math.round(warning.change * 100)}%
            </span>
          </div>
          <p className="text-muted-foreground">{warning.why}</p>
        </li>
      ))}
    </ul>
  );
}

function DriftTileBody({
  title,
  href,
  linkLabel,
  api,
  side,
  quiet,
}: {
  title: string;
  href: string;
  linkLabel: string;
  api: Api;
  side: "kitchen" | "supplier";
  quiet: string;
}) {
  // Call by name: an http Api is a Proxy that hands out a new function per read.
  const state = useAsync(
    () =>
      loadDrift(() =>
        side === "kitchen" ? api.getDrift() : api.getSupplierDrift(),
      ),
    [api, side],
  );
  const showKitchen = side === "supplier";
  if (state.status === "ready" && state.data === null) return null;
  const week =
    state.status === "ready" && state.data
      ? ` · week of ${formatDate(state.data.week)}`
      : "";
  return (
    <Tile title={`${title}${week}`} href={href} linkLabel={linkLabel}>
      <SampleData of={side === "kitchen" ? "getDrift" : "getSupplierDrift"} />
      <TileState<DriftReport>
        status={state.status}
        error={state.error}
        reload={state.reload}
        data={state.status === "ready" ? state.data : null}
        empty={false}
      >
        {(report) =>
          report.warnings.length === 0 ? (
            <p className="text-sm text-muted-foreground">{quiet}</p>
          ) : (
            <DriftList warnings={report.warnings} showKitchen={showKitchen} />
          )
        }
      </TileState>
    </Tile>
  );
}

/** Kitchen side: portion or price creep before the standing order renews. */
export function DriftTile({ api }: { api: Api }) {
  return (
    <DriftTileBody
      title="Standing-order drift"
      href="/approvals"
      linkLabel="Check the next order"
      api={api}
      side="kitchen"
      quiet="Orders per guest are steady. Nothing to check before renewal."
    />
  );
}

/** Valio side: the same warnings for kitchens that share their forecast. */
export function SupplierDriftTile({ api }: { api: Api }) {
  return (
    <DriftTileBody
      title="Kitchens drifting"
      href="/demand"
      linkLabel="Open demand view"
      api={api}
      side="supplier"
      quiet="No sharing kitchen is drifting this week."
    />
  );
}
