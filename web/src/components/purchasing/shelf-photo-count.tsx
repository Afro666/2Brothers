import { Camera, ScanEye } from "lucide-react";
import { useRef, useState } from "react";

import { useApi } from "@/api";
import type { AuditActor, ShelfPhotoRead, ShelfPhotoRow } from "@/api/types";
import { Button } from "@/components/ui/button";
import { formatNumber } from "@/lib/format";
import { downscalePhoto, suggestedCounts } from "@/lib/shelf-photo";
import type { StockItem } from "@/types";

/** The name people know; the gateway's `model` field is the id (`nemotron-3.5-super-vl`). */
export const SHELF_MODEL_NAME = "Nemotron 3.5 Super VL";

/** Under a count that came from the photo and that the person has not changed yet. */
export function PhotoMark() {
  return (
    <p className="mt-1 flex w-56 max-w-full items-start gap-1 text-xs font-medium whitespace-normal text-warning" data-testid="photo-mark">
      <ScanEye className="mt-0.5 size-3.5 shrink-0" aria-hidden />
      <span>read from the photo by {SHELF_MODEL_NAME}, check and save</span>
    </p>
  );
}

const unitLabel = (unit: string | null) => (unit === "PCS" ? "pcs" : (unit ?? ""));

function RowLine({ row, name, onList }: { row: ShelfPhotoRow; name: string | null; onList: boolean }) {
  const counted = row.kind === "COUNTED" && row.count != null;
  return (
    <li className="flex flex-col gap-0.5 py-2 text-sm sm:flex-row sm:items-baseline sm:gap-3">
      {counted ? (
        <span className="shrink-0 font-semibold tabular-nums sm:w-28">
          {formatNumber(row.count as number)} {unitLabel(row.unit)}
        </span>
      ) : (
        <span className="shrink-0 font-semibold text-warning sm:w-28">please count</span>
      )}
      <span className="min-w-0 break-words">
        <span className="font-medium">{name ?? "No product on your stock list matches"}</span>
        <span className="block text-xs text-muted-foreground">
          {counted && row.packs != null && row.packSize != null
            ? `${row.packs} ${row.packs === 1 ? "pack" : "packs"} x ${formatNumber(row.packSize)} ${unitLabel(row.unit)}. `
            : null}
          {counted && !onList ? "Not on this stock list, so no count was filled in. " : null}
          Read on the pack: “{row.label}” ({row.confidence} confidence)
        </span>
      </span>
    </li>
  );
}

function summary(read: ShelfPhotoRead, filled: number): string {
  const seconds = (read.durationMs / 1000).toFixed(1);
  const byHand = read.rows.filter((row) => row.kind !== "COUNTED").length;
  const products = `${read.rows.length} ${read.rows.length === 1 ? "product" : "products"}`;
  return [
    `${SHELF_MODEL_NAME} read ${products} in ${seconds} s.`,
    `${filled} ${filled === 1 ? "count" : "counts"} filled in below; ${byHand} to count by hand.`,
    "Nothing is saved until you press Save count.",
  ].join(" ");
}

/**
 * "Count from a photo" on the Stock page (#373). The person takes or picks a photo of a
 * shelf; the browser scales it down; the gateway has Nemotron 3.5 Super VL read it. The
 * counts it read go to `onCounts` as suggestions. This component saves nothing.
 */
export function ShelfPhotoCount({
  items,
  actor,
  disabled,
  onCounts,
}: {
  items: StockItem[];
  actor: AuditActor;
  disabled?: boolean;
  onCounts: (counts: Record<string, number>) => void;
}) {
  const api = useApi();
  const camera = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const latest = useRef(0);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ read: ShelfPhotoRead; filled: number } | null>(null);
  const names = new Map(items.map((item) => [item.productId, item.productName]));

  async function readPhoto(file: File | undefined) {
    if (!file || reading) return;
    const turn = ++latest.current;
    setReading(true);
    setError(null);
    setResult(null);
    try {
      const read = await api.readShelfPhoto(await downscalePhoto(file), actor);
      if (turn !== latest.current) return;
      const counts = suggestedCounts(read.rows, new Set(names.keys()));
      onCounts(counts);
      setResult({ read, filled: Object.keys(counts).length });
    } catch (problem) {
      if (turn === latest.current) setError(problem instanceof Error ? problem.message : String(problem));
    } finally {
      if (turn === latest.current) setReading(false);
    }
  }

  const input = (ref: React.RefObject<HTMLInputElement | null>, label: string, capture: boolean) => (
    <input
      ref={ref}
      type="file"
      accept="image/*"
      // On a phone this opens the back camera; a laptop shows the file dialog.
      capture={capture ? "environment" : undefined}
      className="sr-only"
      tabIndex={-1}
      aria-label={label}
      onChange={(event) => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = ""; // the same photo can be chosen again
        void readPhoto(file);
      }}
    />
  );

  return (
    <section aria-labelledby="shelf-photo-title" className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <h2 id="shelf-photo-title" className="text-base font-semibold">
            Count from a photo
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">
            {SHELF_MODEL_NAME} reads a photo of a shelf and fills in the counts it is sure of. You check them, then
            save.
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button type="button" disabled={disabled || reading} onClick={() => camera.current?.click()}>
            <Camera aria-hidden />
            Count from a photo
          </Button>
          <Button type="button" variant="outline" disabled={disabled || reading} onClick={() => picker.current?.click()}>
            Choose a file
          </Button>
        </div>
        {input(camera, "Take a photo of the shelf", true)}
        {input(picker, "Choose a photo of the shelf", false)}
      </div>
      {reading || result ? (
        <p role="status" className="text-sm">
          {reading ? `${SHELF_MODEL_NAME} is reading the photo. This takes a few seconds.` : null}
          {!reading && result ? summary(result.read, result.filled) : null}
        </p>
      ) : null}
      {error ? (
        <p role="alert" className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          The photo was not read: {error} You can still type the counts by hand.
        </p>
      ) : null}
      {result && result.read.rows.length === 0 ? (
        <p className="text-sm font-medium text-warning">No product was seen on this photo. Count by hand.</p>
      ) : null}
      {result && result.read.rows.length > 0 ? (
        <ul className="divide-y border-t" aria-label="What was read from the photo">
          {result.read.rows.map((row, index) => (
            <RowLine
              key={`${index}-${row.label}`}
              row={row}
              name={(row.productId && names.get(row.productId)) || row.productName}
              onList={row.productId != null && names.has(row.productId)}
            />
          ))}
        </ul>
      ) : null}
    </section>
  );
}
