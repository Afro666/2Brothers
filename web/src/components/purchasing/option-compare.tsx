import { Check } from "lucide-react";
import { useEffect, useId, useState, type ReactNode } from "react";

import { LabelChip } from "@/components/purchasing/chips";
import { Button } from "@/components/ui/button";
import { ApiError } from "@/api/types";
import { formatDateTime, formatEur, formatNumber, formatPercent } from "@/lib/format";
import { cn } from "@/lib/utils";
import type { OfferTier, ProposalOption } from "@/types";

/** How long to wait for the re-simulated options before freeing the buttons again. */
export const CHOOSE_TIMEOUT_MS = 5000;

const TIER_ORDER: OfferTier[] = ["good", "better", "best"];
const BADGE = "label-caps rounded-sm border border-input px-2 py-0.5 whitespace-nowrap";
const CHOOSE_ERRORS: Record<string, string> = {
  STOCK_UNKNOWN: "Stock is not confirmed for this option. The current basket is unchanged; wait for the supplier or choose another option. Nothing was approved.",
  CLOSING_PASSED: "The order cut-off for this option has passed. The current basket is unchanged; choose another option. Nothing was approved.",
  OPTION_UNAVAILABLE: "This option is no longer available. The current basket is unchanged; choose another option. Nothing was approved.",
  NOT_PENDING: "This proposal is no longer waiting for approval. Its current status is being reloaded. Nothing was changed or approved by this choice.",
  HUMAN_SESSION_REQUIRED: "Only a person signed in to the kitchen can choose an option. Nothing was changed or approved.",
  OPTION_NOT_FOUND: "This option is not part of this proposal any more. The current basket is unchanged; choose another option. Nothing was approved.",
  PROPOSAL_NOT_FOUND: "This proposal could not be found in this kitchen. The current basket is unchanged. Nothing was approved.",
  IDEMPOTENCY_KEY_REUSED: "This choice clashed with an earlier one that was still being sent. The current basket is unchanged; try again. Nothing was approved.",
};

/** Why a person cannot approve this option now; null when they can. */
function blockedReason(option: ProposalOption): string | null {
  if (!option.stockConfirmed) return "Stock is not confirmed. Approval is available once the supplier confirms it.";
  if (option.cutoffPassed) return "The order cut-off has passed.";
  return null;
}

function Fact({
  label,
  bad,
  children,
  className,
}: {
  label: string;
  bad?: boolean;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div>
      <dt className="label-caps">{label}</dt>
      <dd className={cn("min-w-0 tabular-nums", bad && "font-medium text-danger", className)}>
        {children === "unknown" ? <span className="unknown-value">unknown</span> : children}
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
  const [awaiting, setAwaiting] = useState<{ from: ProposalOption[] } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const sorted = [...options].sort((a, b) => TIER_ORDER.indexOf(a.tier) - TIER_ORDER.indexOf(b.tier));

  // The approval names the proposal's exact total, so it opens only once the
  // re-simulated proposal is on screen, and not at all if that basket is blocked
  // or the new options do not hold it.
  useEffect(() => {
    if (!awaiting) return;
    // Re-simulation refreshes offer ids: trust `chosen`, mapped from the answered proposal,
    // rather than looking for the option id that was sent.
    const previouslyChosen = awaiting.from.find((option) => option.chosen)?.id;
    const chosen = options.find((option) => option.chosen && option.id !== previouslyChosen);
    if (!chosen && options === awaiting.from) return;
    setAwaiting(null);
    if (chosen && !blockedReason(chosen)) onApprove?.();
  }, [awaiting, options, onApprove]);

  // If the reload after choosing fails or brings back the same options, free the
  // buttons after a while and say so, so the person can try again.
  useEffect(() => {
    if (!awaiting) return;
    const timer = setTimeout(() => {
      setAwaiting(null);
      setError("Could not load the updated options. Nothing was approved. Please try again.");
    }, CHOOSE_TIMEOUT_MS);
    return () => clearTimeout(timer);
  }, [awaiting]);

  async function choose(option: ProposalOption) {
    if (option.chosen) return onApprove?.();
    setBusy(true);
    setError(null);
    try {
      await onChoose?.(option.id);
      setAwaiting({ from: options });
    } catch (e) {
      setError(
        e instanceof ApiError && CHOOSE_ERRORS[e.code]
          ? `Could not choose this option. ${CHOOSE_ERRORS[e.code]}`
          : `Could not choose this option: ${e instanceof Error ? e.message : String(e)}. Nothing was changed or approved.`,
      );
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="space-y-2" aria-labelledby={headingId}>
      <h4 id={headingId} className="label-caps">
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
                "grid gap-x-5 gap-y-2 rounded-sm border p-3 text-sm sm:grid-cols-[9.5rem_minmax(0,1fr)]",
                recommended && "border-l-[3px] border-l-primary",
              )}
            >
              <div className="flex min-w-0 flex-wrap items-center gap-2 sm:col-span-2">
                <h5 className="font-medium">
                  Option {letter}:{" "}
                  {option.lines
                    .map((line) => `${formatNumber(line.quantity)} ${line.unit} ${line.productName ?? line.productId}`)
                    .join(" + ")}
                </h5>
                {recommended ? (
                  <span className="stamp rounded-sm bg-primary px-2 py-0.5 text-xs whitespace-nowrap text-primary-foreground">
                    Recommended by the Buyer
                  </span>
                ) : null}
                {option.kind === "PARTIAL" ? <span className={BADGE}>Part now, the rest later</span> : null}
                {option.chosen ? <span className={BADGE}>Proposed now</span> : null}
              </div>
              <dl className="grid grid-cols-2 items-start gap-x-4 gap-y-2 sm:grid-cols-1">
                <Fact label="Price ex VAT" className="price-tag">
                  {prices.length === 1 ? prices[0] : prices.join(", ")}
                </Fact>
                <Fact label="Total" className="font-semibold">
                  {formatEur(option.totalInclVat)} incl VAT
                </Fact>
              </dl>
              <dl className="grid grid-cols-2 gap-x-4 gap-y-2 lg:grid-cols-3">
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
              <p className="max-w-[68ch] text-[15px] leading-[22px] sm:col-start-2">{option.tradeOff}</p>
              {option.held ? (
                <p className="hatch text-sm text-warning sm:col-start-2">
                  {formatNumber(option.held.quantity)} {option.held.unit} waits for stock confirmation
                </p>
              ) : null}
              {blocked ? (
                <p className="hatch text-warning sm:col-start-2">
                  Cannot be approved now: {blocked}
                </p>
              ) : canAct ? (
                <Button
                  type="button"
                  variant={recommended ? "default" : "outline"}
                  className="h-auto w-full whitespace-normal py-2 sm:col-start-2 sm:w-auto sm:justify-self-start"
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
        <p role="alert" className="rounded-sm border border-danger/40 bg-danger-surface px-3 py-2 text-sm text-danger">
          {error}
        </p>
      ) : null}
    </section>
  );
}
