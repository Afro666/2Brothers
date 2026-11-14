import { Check } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

import { LabelChip } from "@/components/purchasing/chips";
import { Button } from "@/components/ui/button";
import { formatDateTime, formatEur, formatNumber, formatPercent } from "@/lib/format";
import { TONE_CLASSES } from "@/lib/tone";
import { cn } from "@/lib/utils";
import type { OfferTier, ProposalOption } from "@/types";

const TIER_ORDER: OfferTier[] = ["good", "better", "best"];
const BADGE = "rounded-full border px-2 py-0.5 text-xs font-medium whitespace-nowrap";

/** Why a person cannot approve this option now; null when they can. */
function blockedReason(option: ProposalOption): string | null {
  if (!option.stockConfirmed) return "Stock is not confirmed. Approval is available once the supplier confirms it.";
  if (option.cutoffPassed) return "The order cut-off has passed.";
  return null;
}

function Fact({ label, bad, children }: { label: string; bad?: boolean; children: ReactNode }) {
  return (
    <div>
      <dt className="text-xs text-muted-foreground">{label}</dt>
      <dd className={cn("tabular-nums", bad && "font-medium text-danger", children === "unknown" && "text-warning")}>
        {children}
      </dd>
    </div>
  );
}

/**
 * The engine's options for one request, one row each, in the API's order (A, B, C).
 * The UI never ranks them: "recommended" is shown only when the API says so, and never
 * on an option whose stock is unknown. The row's button chooses the option and opens the
 * existing approval; it approves nothing by itself.
 */
export function OptionCompare({
  options,
  disabled = false,
  onChoose,
  onApprove,
}: {
  options: ProposalOption[];
  disabled?: boolean;
  /** Re-simulates the proposal with this option. Absent: the API cannot switch baskets. */
  onChoose?: (optionId: string) => void | Promise<void>;
  /** Opens the existing approval for the basket the proposal holds now. */
  onApprove?: () => void;
}) {
  const headingId = useId();
  const [busy, setBusy] = useState(false);
  const [awaiting, setAwaiting] = useState<{ id: string; from: ProposalOption[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sorted = [...options].sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier));

  // The approval names the proposal's exact total, so it opens only once the
  // re-simulated proposal is on screen, and not at all if that basket is blocked
  // or the new options do not hold it.
  useEffect(() => {
    if (!awaiting) return;
    const chosen = options.find((option) => option.id === awaiting.id && option.chosen);
    if (!chosen && options === awaiting.from) return;
    setAwaiting(null);
    if (chosen && !blockedReason(chosen)) onApprove?.();
  }, [awaiting, options, onApprove]);

  async function choose(option: ProposalOption) {
    if (option.chosen) return onApprove?.();
    setBusy(true);
    setError(null);
    try {
      await onChoose?.(option.id);
      setAwaiting({ id: option.id, from: options });
    } catch (e) {
      setError(
        `Could not choose this option: ${e instanceof Error ? e.message : String(e)}. Nothing was changed or approved.`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-2" aria-labelledby={headingId}>
      <h4 id={headingId} className="text-sm font-medium">
        Your options
      </h4>
      <ul className="space-y-2">
        {sorted.map((option, index) => {
          const letter = String.fromCharCode(65 + index);
          const blocked = blockedReason(option);
          const recommended = option.recommended && option.stockConfirmed;
          const canAct = option.chosen ? onApprove != null : onChoose != null;
          const prices = [
            ...new Set(
              option.lines.map((line) =>
                line.unitPrice == null ? "unknown" : `${formatEur(line.unitPrice)} per ${line.unit}`,
              ),
            ),
          ];
          const co2 = option.co2KgPerKg;
          return (
            <li
              key={option.id}
              className={cn(
                "space-y-3 rounded-md border p-3 text-sm",
                recommended && "border-primary ring-1 ring-primary",
              )}
            >
              <div className="flex flex-wrap items-center gap-2">
                <h5 className="font-medium">
                  Option {letter}:{" "}
                  {option.lines
                    .map((line) => `${formatNumber(line.quantity)} ${line.unit} ${line.productName ?? line.productId}`)
                    .join(" + ")}
                </h5>
                {recommended ? (
                  <span className={cn(BADGE, "border-primary bg-primary text-primary-foreground")}>
                    Recommended by the Buyer
                  </span>
                ) : null}
                {option.kind === "PARTIAL" ? <span className={BADGE}>Part now, the rest later</span> : null}
                {option.chosen ? <span className={BADGE}>Proposed now</span> : null}
              </div>
              <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
                <Fact label="Price ex VAT">{prices.length === 1 ? prices[0] : prices.join(", ")}</Fact>
                <Fact label="Total">{formatEur(option.totalInclVat)} incl VAT</Fact>
                <Fact label="Stock">{option.stockConfirmed ? "confirmed" : "unknown"}</Fact>
                <Fact label="Order cut-off" bad={option.cutoffPassed === true}>
                  {option.cutoffPassed == null
                    ? "unknown"
                    : `${option.cutoffPassed ? "missed" : "met"}${
                        option.cutoffAt
                          ? ` (${option.cutoffPassed ? "closed" : "order by"} ${formatDateTime(option.cutoffAt)})`
                          : ""
                      }`}
                </Fact>
                <Fact label="Delivery reliability">{formatPercent(option.deliveryReliability)}</Fact>
                <Fact label="CO2 (product-group average)">
                  {co2 == null
                    ? "unknown"
                    : `${formatNumber(co2.min)}${co2.max === co2.min ? "" : `–${formatNumber(co2.max)}`} kg CO2e/kg`}
                </Fact>
                <Fact label="Labels">
                  {option.labels == null ? (
                    "unknown"
                  ) : option.labels.length === 0 ? (
                    "none"
                  ) : (
                    <span className="flex flex-wrap gap-1">
                      {option.labels.map((label) => (
                        <LabelChip key={label} label={label} />
                      ))}
                    </span>
                  )}
                </Fact>
              </dl>
              <p>{option.tradeOff}</p>
              {blocked ? (
                <p className={cn("rounded-md border px-3 py-2", TONE_CLASSES.warning)}>
                  Cannot be approved now: {blocked}
                </p>
              ) : canAct ? (
                <Button
                  type="button"
                  variant={recommended ? "default" : "outline"}
                  className="h-auto w-full whitespace-normal py-2 sm:w-auto"
                  disabled={disabled || busy || awaiting != null}
                  onClick={() => void choose(option)}
                >
                  <Check aria-hidden />
                  Choose option {letter}: approve {formatEur(option.totalInclVat)} incl VAT
                </Button>
              ) : null}
            </li>
          );
        })}
      </ul>
      {error ? (
        <p role="alert" className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.danger)}>
          {error}
        </p>
      ) : null}
    </section>
  );
}
