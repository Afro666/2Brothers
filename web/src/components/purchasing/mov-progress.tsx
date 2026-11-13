import { Truck } from "lucide-react";

import { formatEur } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { MovState } from "@/types";

/**
 * The order against the free-delivery threshold (MOV). MOV is a threshold,
 * not a wall: below it the order can still go, and pays the delivery fee.
 */
export function MovProgress({ mov, className }: { mov: MovState; className?: string }) {
  const gap = Math.max(0, Math.round((mov.threshold - mov.current) * 100) / 100);
  const met = gap === 0;
  const pct = mov.threshold > 0 ? Math.min(100, (mov.current / mov.threshold) * 100) : 100;
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
        <span className="inline-flex items-center gap-1.5 font-medium">
          <Truck className="size-4 text-muted-foreground" aria-hidden />
          {met ? "Free delivery reached" : `${formatEur(gap)} to free delivery`}
        </span>
        <span className="text-muted-foreground tabular-nums">
          {formatEur(mov.current)} of {formatEur(mov.threshold)} ex VAT
        </span>
      </div>
      <div
        role="progressbar"
        aria-label="Order value toward free delivery"
        aria-valuemin={0}
        aria-valuemax={mov.threshold}
        aria-valuenow={Math.min(mov.current, mov.threshold)}
        aria-valuetext={met ? "Free delivery reached" : `${formatEur(gap)} to go`}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn("h-full rounded-full transition-[width]", met ? "bg-success" : "bg-warning")}
          style={{ width: `${pct}%` }}
        />
      </div>
      {met ? null : (
        <p className="text-xs text-muted-foreground">
          Below the threshold the order still goes, with a {formatEur(mov.deliveryFee)} delivery fee.
        </p>
      )}
    </div>
  );
}
