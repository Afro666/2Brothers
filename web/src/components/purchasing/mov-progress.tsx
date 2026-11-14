import { Truck } from "lucide-react";

import { formatEur } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import type { MovState } from "@/types";

/**
 * The order against the free-delivery threshold (MOV). MOV is a threshold,
 * not a wall: below it the order can still go, and pays the delivery fee.
 */
export function MovProgress({ mov, className }: { mov: MovState | null; className?: string }) {
  const t = useT();
  if (mov == null) {
    return (
      <p className={cn("inline-flex items-center gap-1.5 text-sm text-muted-foreground", className)}>
        <Truck className="size-4" aria-hidden />
        {t("Free-delivery threshold and delivery fee unknown: the supplier's terms are not set.")}
      </p>
    );
  }
  const gap = Math.max(0, Math.round((mov.threshold - mov.current) * 100) / 100);
  const met = gap === 0;
  const pct = mov.threshold > 0 ? Math.min(100, (mov.current / mov.threshold) * 100) : 100;
  return (
    <div className={cn("space-y-2", className)}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
        <span className="inline-flex items-center gap-1.5 font-medium">
          <Truck className="size-4 text-muted-foreground" aria-hidden />
          {met ? t("Free delivery reached") : t("{amount} to free delivery", { amount: formatEur(gap) })}
        </span>
        <span className="text-muted-foreground tabular-nums">
          {/* Once reached, a gateway order knows the threshold only as "met", so it is not named. */}
          {met
            ? t("{amount} ex VAT", { amount: formatEur(mov.current) })
            : t("{current} of {threshold} ex VAT", {
                current: formatEur(mov.current),
                threshold: formatEur(mov.threshold),
              })}
        </span>
      </div>
      <div
        role="progressbar"
        aria-label={t("Order value toward free delivery")}
        aria-valuemin={0}
        aria-valuemax={mov.threshold}
        aria-valuenow={Math.min(mov.current, mov.threshold)}
        aria-valuetext={met ? t("Free delivery reached") : t("{amount} to go", { amount: formatEur(gap) })}
        className="h-2 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn("h-full rounded-full transition-[width]", met ? "bg-success" : "bg-warning")}
          style={{ width: `${pct}%` }}
        />
      </div>
      {met ? null : (
        <p className="text-xs text-muted-foreground">
          {t("Below the threshold the order still goes, with a {fee} delivery fee.", {
            fee: formatEur(mov.deliveryFee),
          })}
        </p>
      )}
    </div>
  );
}
