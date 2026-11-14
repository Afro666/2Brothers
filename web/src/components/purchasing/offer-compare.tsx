import { ArrowDown, ArrowUp, Minus } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate, formatEur, formatPack, isLater, isPassed } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { OfferTier, SubstituteOption } from "@/types";

const TIER_LABEL: Record<OfferTier, string> = { good: "Good", better: "Better", best: "Best" };
const TIER_ORDER: OfferTier[] = ["good", "better", "best"];

const DIRECTION_ICON = { plus: ArrowUp, minus: ArrowDown, neutral: Minus } as const;
const DIRECTION_CLASS = { plus: "text-success", minus: "text-danger", neutral: "text-muted-foreground" } as const;
const DIRECTION_SR = { plus: "Better: ", minus: "Worse: ", neutral: "" } as const;

/**
 * Good / better / best substitutes side by side. The facts row is the same
 * on every card (price per L, fat %, pack, organic, delivery) so they line
 * up; the trade-off lines are the agent's words about what changes.
 */
export function OfferCompare({
  options,
  now,
  onChoose,
}: {
  options: SubstituteOption[];
  now: Date;
  onChoose?: (option: SubstituteOption) => void;
}) {
  const sorted = [...options].sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier));
  return (
    <div className="grid gap-4 md:grid-cols-3">
      {sorted.map((o) => {
        const { product, offer } = o;
        const closed = isPassed(offer.closingTime, now);
        const late = isLater(offer.availableDate, offer.requestedDate);
        const facts: [string, string, boolean?][] = [
          [
            `Price per ${offer.comparisonUnit ?? product.baseUnit}`,
            offer.comparisonPrice == null ? "unknown" : formatEur(offer.comparisonPrice),
          ],
          ["Fat", product.fatPercent == null ? "unknown" : `${product.fatPercent} %`],
          ["Pack", formatPack(product.salesUnit, product.baseUnitsPerSalesUnit, product.baseUnit)],
          ["Organic", product.labels.includes("EU_ORGANIC_FARMING") ? "yes" : "no"],
          [
            "Delivery",
            closed ? `misses ${formatDate(offer.requestedDate)} (order cut-off passed)` : formatDate(offer.availableDate),
            closed || late,
          ],
        ];
        return (
          <Card key={o.tier} className={cn("gap-4", o.recommended && "border-primary ring-1 ring-primary")}>
            <CardHeader>
              <div className="flex items-start justify-between gap-2">
                <CardTitle className="leading-snug">{product.names.en}</CardTitle>
                <span
                  className={cn(
                    "shrink-0 rounded-full border px-2 py-0.5 text-xs font-medium",
                    closed && "text-muted-foreground",
                    o.recommended && "border-primary bg-primary text-primary-foreground",
                  )}
                >
                  {closed ? "Misses the date" : TIER_LABEL[o.tier]}
                </span>
              </div>
              <p className="text-xs text-muted-foreground">
                {product.id}
                {o.recommended ? " · the agent's pick" : null}
              </p>
            </CardHeader>
            <CardContent className="space-y-4">
              <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1 text-sm">
                {facts.map(([k, v, bad]) => (
                  <div key={k} className="contents">
                    <dt className="text-muted-foreground">{k}</dt>
                    <dd className={cn(bad && "font-medium text-danger", v === "unknown" && "text-warning")}>{v}</dd>
                  </div>
                ))}
              </dl>
              <ul className="space-y-1 text-sm">
                {o.tradeOffs.map((t) => {
                  const Icon = DIRECTION_ICON[t.direction];
                  return (
                    <li key={t.text} className="flex items-start gap-1.5">
                      <Icon className={cn("mt-0.5 size-4 shrink-0", DIRECTION_CLASS[t.direction])} aria-hidden />
                      <span>
                        <span className="sr-only">{DIRECTION_SR[t.direction]}</span>
                        {t.text}
                      </span>
                    </li>
                  );
                })}
              </ul>
            </CardContent>
            {onChoose ? (
              <CardFooter className="mt-auto">
                <Button
                  variant={o.recommended ? "default" : "outline"}
                  className="w-full"
                  disabled={closed || offer.salesBlock}
                  onClick={() => onChoose(o)}
                >
                  {closed ? "Cannot make this delivery" : `Use ${TIER_LABEL[o.tier].toLowerCase()}`}
                </Button>
              </CardFooter>
            ) : null}
          </Card>
        );
      })}
    </div>
  );
}
