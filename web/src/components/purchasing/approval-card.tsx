import { Check, ChevronDown, Plus, X } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { ModelTracePanel } from "@/components/purchasing/model-trace-panel";
import { MovProgress } from "@/components/purchasing/mov-progress";
import { OptionCompare } from "@/components/purchasing/option-compare";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { ProposalExplanationBlock, useCardExplanation } from "@/components/purchasing/proposal-explanation";
import { ProposalLines } from "@/components/purchasing/proposal-lines";
import { RecallLines, recallHold } from "@/components/purchasing/recall-lines";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  formatDate,
  formatDateTime,
  formatEur,
  formatNumber,
  formatStock,
  formatTime,
  isStockUnconfirmed,
  peopleUnit,
} from "@/lib/format";
import { translateReason } from "@/lib/codes";
import { useT } from "@/lib/i18n";
import { inclVatOf, inclVatText } from "@/lib/vat";
import { splitChecks, statusChips } from "@/lib/proposal-checks";
import { cn } from "@/lib/utils";
import { TONE_CLASSES } from "@/lib/tone";
import { useAsync } from "@/lib/use-async";
import { ApiError } from "@/api/types";
import type {
  AddableProduct,
  ApprovalRequest,
  Order,
  OrderLine,
  ProposalChange,
  ProposalChangeReason,
  RecallAlert,
} from "@/types";
import { ProductLink } from "@/components/purchasing/product-link";

/** What the gateway gets on approve: the exact totals the human read. */
export interface ApprovalDecision {
  approvalId: string;
  approvalRef: string | null;
  expectedTotalExVat: number;
  expectedTotalInclVat: number;
}

function requestDescription(request: ApprovalRequest, t: ReturnType<typeof useT>): string {
  const oneLine = request.lineCount === 1;
  const values = {
    count: request.lineCount,
    date: formatDate(request.deliveryDate),
    name: request.requestedBy == null ? "" : t(request.requestedBy),
    created: request.createdAt == null ? "" : t(formatDateTime(request.createdAt)),
  };
  if (request.requestedBy != null && request.createdAt != null) {
    return t(
      oneLine
        ? "{count} line · delivery {date} · asked by {name}, {created}"
        : "{count} lines · delivery {date} · asked by {name}, {created}",
      values,
    );
  }
  if (request.requestedBy != null) {
    return t(
      oneLine
        ? "{count} line · delivery {date} · asked by {name}"
        : "{count} lines · delivery {date} · asked by {name}",
      values,
    );
  }
  if (request.createdAt != null) {
    return t(
      oneLine ? "{count} line · delivery {date} · {created}" : "{count} lines · delivery {date} · {created}",
      values,
    );
  }
  return t(oneLine ? "{count} line · delivery {date}" : "{count} lines · delivery {date}", values);
}

/** Wait this long after the last keystroke before searching addable products. */
export const ADD_SEARCH_DEBOUNCE_MS = 250;

type CutoffLine = NonNullable<ApprovalRequest["cutoffs"]>[number];

export interface EarliestCutoff {
  closingTime: string;
  supplierName: string | null;
  earliestOf: number | null;
  passed: boolean;
  warning: boolean;
  minutesLeft: number;
}

export function earliestCutoff(lines: readonly CutoffLine[], now: Date): EarliestCutoff | null {
  const known = lines.flatMap((line) => {
    if (line.closingTime == null) return [];
    const timestamp = new Date(line.closingTime).getTime();
    return Number.isFinite(timestamp)
      ? [{ closingTime: line.closingTime, supplierName: line.supplierName, timestamp }]
      : [];
  });
  if (known.length === 0) return null;
  const earliest = known.reduce((first, line) => line.timestamp < first.timestamp ? line : first);
  const millisecondsLeft = earliest.timestamp - now.getTime();
  const passed = millisecondsLeft <= 0;
  return {
    closingTime: earliest.closingTime,
    supplierName: earliest.supplierName,
    earliestOf: new Set(known.map((line) => line.timestamp)).size > 1 ? known.length : null,
    passed,
    warning: passed || millisecondsLeft < 2 * 60 * 60 * 1000,
    minutesLeft: Math.max(0, Math.floor(millisecondsLeft / 60_000)),
  };
}

/** Product pictures in the compact card before "+N". */
const THUMBS_SHOWN = 4;
/** Status chips in the compact card; the rest are in Inspect. */
const CHIPS_SHOWN = 3;

const CHANGE_ERRORS: Record<string, string> = {
  NOT_PENDING: "This proposal is no longer waiting for approval. Refresh the page to see its current status.",
  LINE_NOT_FOUND: "That product is not on this proposal. Add it as a new product instead.",
  NOT_ADDABLE: "That product cannot be added to this proposal. Choose a product from the addable list.",
  CLOSING_PASSED: "The order cut-off for this line has passed. Choose another product or reject the proposal.",
  LINE_UNAVAILABLE:
    "This product cannot be ordered now. It may be recalled, blocked by an allergen rule, or have no stock date.",
  EMPTY_PROPOSAL: "Every line would be removed: reject the proposal instead.",
  PROPOSAL_NOT_FOUND: "This proposal could not be found in this kitchen.",
  ROLE_REQUIRED: "Your role cannot change proposals. Ask a chef or approver to make this change.",
};

const CHANGE_REASONS: readonly { value: ProposalChangeReason; label: string }[] = [
  { value: "TOO_MUCH", label: "Too much" },
  { value: "TOO_LITTLE", label: "Too little" },
  { value: "IN_STOCK", label: "Still in stock" },
  { value: "MENU_CHANGED", label: "Menu changed" },
  { value: "BUDGET", label: "Budget" },
  { value: "OTHER", label: "Other" },
];

interface LineChangeState {
  reason?: ProposalChangeReason;
  note: string;
  removing: boolean;
}

/**
 * One order outside the mandate, waiting for a human. Compact by default: what it is,
 * when it comes, the total, a few status chips and Approve / Reject, so a buyer decides
 * in seconds. Inspect opens the rest: the lines table (editable), the options, the full
 * "What to check" list and what the model did.
 *
 * Approve names the exact total on the button and again in the confirmation, because
 * that figure is what the gateway checks (`expected_total`) when it places the order.
 * The human's "yes" to that figure is the consent; the total alone is not.
 */
export function ApprovalCard({
  request,
  order,
  now,
  onApprove,
  onReject,
  onChangeProposal,
  onChooseOption,
  listAddableProducts,
  editCount = 0,
  approvalBlockedReason,
  recalls = [],
}: {
  request: ApprovalRequest;
  order?: Order;
  now?: Date;
  onApprove?: (decision: ApprovalDecision) => void | Promise<void>;
  onReject?: (approvalId: string, reason: string) => void | Promise<void>;
  onChangeProposal?: (change: ProposalChange) => void | Promise<void>;
  onChooseOption?: (optionId: string) => void | Promise<void>;
  listAddableProducts?: (query: string) => Promise<AddableProduct[]>;
  editCount?: number;
  approvalBlockedReason?: string;
  /** Recall alerts on this order; a blocked line still on it holds the approval. */
  recalls?: RecallAlert[];
}) {
  const t = useT();
  // #1630: `totalInclVat` is the approve figure; incl VAT is `inclVat`, or unknown when a rate is.
  const inclVat = inclVatOf(request);
  // The approve figure (`expected_total`) holds the delivery fee; when it is not the figure shown
  // as incl VAT, the card names the sum, so the total above and the approve button agree.
  const approveDiffers = inclVat === null || Math.abs(inclVat - request.totalInclVat) >= 0.005;
  const [open, setOpen] = useState<"approve" | "reject" | null>(null);
  const [status, setStatus] = useState(request.status);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [, setClock] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [changeError, setChangeError] = useState<string | null>(null);
  const changing = useRef(false);
  // Every card starts compact (#1142, Aron 2026-11-14): the details open on Inspect.
  const [inspecting, setInspecting] = useState(false);
  const [adding, setAdding] = useState(false);
  const [search, setSearch] = useState("");
  // The checked Nemotron explanation (#1173): asked after the card is drawn, never awaited.
  const explanation = useCardExplanation(
    request.id,
    request.status === "PENDING",
    // The gateway's offer for this card: its approval, its lines and its totals. A changed
    // basket with the same total is still another offer, and must drop the old text.
    `${request.approvalRef}\u0000${order?.lines.map((line) => `${line.product.id}:${line.quantity}`).join(",")}\u0000${request.totalExVat}\u0000${request.totalInclVat}`,
  );
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const [lineChanges, setLineChanges] = useState<Record<string, LineChangeState>>({});
  const [debouncedSearch, setDebouncedSearch] = useState(search);
  useEffect(() => {
    const timer = window.setTimeout(() => setDebouncedSearch(search), ADD_SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search]);
  const baseId = useId();
  const reasonId = `${baseId}-reason`;
  const inspectId = `${baseId}-inspect`;
  const addId = `${baseId}-add`;
  const stockBlockId = `${baseId}-stock-block`;
  const accountBlockId = `${baseId}-account-block`;
  const pending = status === "PENDING";
  useEffect(() => {
    if (!pending) return;
    const timer = window.setInterval(() => setClock((tick) => tick + 1), 60_000);
    return () => window.clearInterval(timer);
  }, [pending]);
  // A proposal held by a recall cannot be approved, but it can be rejected to close it.
  const held = status === "BLOCKED_BY_RECALL";
  const canDecide = pending || (held && onReject != null);
  const editing = pending && onChangeProposal != null && listAddableProducts != null;
  // The addable list is asked for only once a person opens it.
  const addables = useAsync(
    () => (editing && adding ? listAddableProducts?.(debouncedSearch) ?? Promise.resolve([]) : Promise.resolve([])),
    [debouncedSearch, editing && adding],
  );
  // What holds the approval: a recall, or lines we cannot show.
  const recallMessage = recallHold(recalls, order, t);
  const stockMessage =
    recallMessage ??
    (!order || order.lines.length === 0 ? t("Order details are unavailable. Reload them before approving.") : null);
  // Unconfirmed supplier stock does not hold it (Aron, 2026-11-14): the order is sent and waits.
  const waitingNotice =
    order?.lines.some((line) => isStockUnconfirmed(line.offer))
      ? t("Some lines wait for the supplier's stock confirmation. You can still approve: the order is sent and marked as waiting for the supplier.")
      : null;
  const clock = now ?? new Date();
  const cutoff = earliestCutoff(
    request.cutoffs ?? order?.lines.map((line) => ({ closingTime: line.offer.closingTime, supplierName: null })) ?? [],
    clock,
  );
  // No supplier block names the line: say no name rather than a generic one.
  const cutoffOrigin = cutoff?.supplierName ? ` · ${t("{supplier}'s cut-off", { supplier: cutoff.supplierName })}` : "";
  const cutoffEarliest = cutoff?.earliestOf == null ? "" : t(" (earliest of {count})", { count: cutoff.earliestOf });
  const cutoffTimeLeft = cutoff && !cutoff.passed && cutoff.warning
    ? cutoff.minutesLeft >= 60
      ? t("{hours} h {minutes} min left", {
          hours: Math.floor(cutoff.minutesLeft / 60),
          minutes: cutoff.minutesLeft % 60,
        })
      : cutoff.minutesLeft > 0
        ? t("{minutes} min left", { minutes: cutoff.minutesLeft })
        : t("Less than 1 min left")
    : null;
  const approveBlockDescription = [stockMessage ? stockBlockId : null, approvalBlockedReason ? accountBlockId : null]
    .filter(Boolean).join(" ") || undefined;
  const lines = order?.lines ?? [];
  const checks = splitChecks(request.reasons, lines);
  const chips = statusChips({
    request,
    order,
    now: clock,
    heldByRecall: held || recallMessage != null,
    leftOut: checks.leftOut.length,
  });
  const suppliers = [...new Set(["Valio", ...request.suppliersToConfirm.map((supplier) => supplier.name)])];
  // One sentence on why: the checked Nemotron explanation (#1394) when there is one, else the
  // engine's own reason for a one-line order.
  const why = !explanation?.text && lines.length === 1 ? lines[0].why : null;
  const optionCount = pending ? (request.options?.length ?? 0) : 0;

  async function changeProposal(change: ProposalChange) {
    // The ref closes the gap before `busy` disables the buttons: two fast presses are one change.
    if (!onChangeProposal || changing.current) return;
    changing.current = true;
    setBusy(true);
    setChangeError(null);
    try {
      await onChangeProposal(change);
      // Drop the typed number so the input shows the line's real quantity.
      setQuantities((current) => {
        const next = { ...current };
        delete next[change.productId];
        return next;
      });
      resetLineChange(change.productId);
      addables.reload();
    } catch (e) {
      setChangeError(
        e instanceof ApiError && CHANGE_ERRORS[e.code]
          ? t("Could not change this proposal. {reason} The proposal is unchanged.", {
              reason: t(CHANGE_ERRORS[e.code]),
            })
          : e instanceof ApiError && e.code === "NETWORK"
            ? // The change may have reached the gateway: never say "unchanged" here.
              t("The gateway did not answer, so the change may or may not be saved. Check the lines and the total below before you approve.")
            : t("Could not change this proposal: {message} The proposal is unchanged.", {
                message: e instanceof Error ? e.message : String(e),
              }),
      );
    } finally {
      changing.current = false;
      setBusy(false);
    }
  }

  async function chooseOption(optionId: string) {
    setBusy(true);
    try {
      await onChooseOption?.(optionId);
    } finally {
      setBusy(false);
    }
  }

  function quantityValue(line: OrderLine) {
    return quantities[line.product.id] ?? String(line.quantity);
  }

  const removeId = (line: OrderLine) => `remove-${request.id}-${line.product.id}`;

  function resetLineChange(productId: string) {
    setLineChanges((current) => {
      if (!current[productId]) return current;
      const next = { ...current };
      delete next[productId];
      return next;
    });
  }

  /** The reason the person tapped, never the suggestion; a note only with OTHER (#1301). */
  function selectedChange(productId: string) {
    const lineChange = lineChanges[productId];
    if (!lineChange?.reason) return {};
    return {
      reason: lineChange.reason,
      ...(lineChange.reason === "OTHER" && lineChange.note ? { note: lineChange.note } : {}),
    };
  }

  /** Under a line with a typed new quantity, or a Remove waiting for its confirm: the chips (#1301). */
  function lineBelow(line: OrderLine) {
    const quantity = Number(quantityValue(line));
    const quantityChanged =
      quantityValue(line).trim() !== "" && Number.isInteger(quantity) && quantity >= 1 && quantity !== line.quantity;
    const lineChange = lineChanges[line.product.id];
    const removing = lineChange?.removing ?? false;
    if (!removing && !quantityChanged) return null;
    return (
      <div className="space-y-2">
        <ChangeReasonChips
          productName={line.product.names.en}
          disabled={busy}
          reason={lineChange?.reason}
          note={lineChange?.note ?? ""}
          suggested={removing || quantity < line.quantity ? "TOO_MUCH" : "TOO_LITTLE"}
          onReason={(reason) =>
            setLineChanges((current) => {
              const existing = current[line.product.id] ?? { note: "", removing };
              return {
                ...current,
                [line.product.id]: { ...existing, reason: existing.reason === reason ? undefined : reason },
              };
            })
          }
          onNote={(note) =>
            setLineChanges((current) => ({
              ...current,
              [line.product.id]: { ...(current[line.product.id] ?? { removing }), note },
            }))
          }
        />
        {removing ? (
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              variant="destructive"
              className="min-h-11"
              disabled={busy}
              aria-label={t("Remove line: {product}", { product: line.product.names.en })}
              onClick={() =>
                void changeProposal({ type: "REMOVE_LINE", productId: line.product.id, ...selectedChange(line.product.id) })
              }
            >
              {t("Remove line")}
            </Button>
            <Button
              type="button"
              variant="outline"
              className="min-h-11"
              disabled={busy}
              aria-label={t("Keep line: {product}", { product: line.product.names.en })}
              onClick={() => {
                // This button unmounts: give focus back to the line's Remove.
                document.getElementById(removeId(line))?.focus();
                resetLineChange(line.product.id);
              }}
            >
              {t("Keep line")}
            </Button>
          </div>
        ) : null}
      </div>
    );
  }

  // The status changes only after the gateway confirms. If the call fails
  // (price moved, expected_total mismatch, network), the card stays PENDING
  // and shows the error, so nobody believes an order went through.
  async function decide(next: "APPROVED" | "REJECTED", call: () => void | Promise<void>) {
    if (approvalBlockedReason || (next === "APPROVED" && (stockMessage || !pending))) return;
    setBusy(true);
    setError(null);
    try {
      await call();
      setStatus(next);
    } catch (e) {
      // No answer, a 5xx or an unreadable answer: the decision may have landed (a retry replays the same key).
      const unknownOutcome =
        e instanceof ApiError &&
        (e.code === "NETWORK" || e.code === "INVALID_RESPONSE" || (e.status != null && e.status >= 500));
      if (unknownOutcome) {
        setError(t("The outcome is unknown: reload before you try again"));
        return;
      }
      const what = next === "APPROVED" ? t("Approval") : t("Rejection");
      const recallBlocked = next === "APPROVED" && e instanceof ApiError && e.code === "BLOCKED_BY_RECALL";
      const message =
        recallBlocked
          ? t("This order is blocked by a recall. Reject it and approve the replacement order instead")
          : e instanceof Error
            ? e.message
            : String(e);
      setError(
        t("{what} failed: {message}. {outcome}", {
          what,
          message,
          outcome: recallBlocked || held ? t("The order stays held by the recall.") : t("The order is still pending."),
        }),
      );
    } finally {
      setBusy(false);
      setOpen(null);
    }
  }

  return (
    <Card
      id={`proposal-${request.orderId}`}
      tabIndex={-1}
      className="docket scroll-mt-6 gap-3 p-4 outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70 sm:p-5"
    >
      <CardHeader className="grid-cols-1 grid-rows-none items-start gap-x-4 gap-y-2 px-0 sm:grid-cols-[minmax(0,1fr)_auto]">
        <div className="flex min-w-0 items-start gap-3">
          {lines.length > 0 ? (
            <span className="flex shrink-0 -space-x-3 pt-0.5 max-sm:hidden" data-testid="proposal-thumbs">
              {lines.slice(0, THUMBS_SHOWN).map((line) => (
                <ProductThumb
                  key={line.product.id}
                  en={line.product.names.en}
                  fi={line.product.names.fi}
                  brand={line.product.brand}
                  size="sm"
                  className="ring-2 ring-card"
                />
              ))}
              {lines.length > THUMBS_SHOWN ? (
                <span
                  aria-hidden
                  className="inline-flex size-8 items-center justify-center rounded-lg bg-muted font-mono text-[11px] text-muted-foreground ring-2 ring-card"
                >
                  +{lines.length - THUMBS_SHOWN}
                </span>
              ) : null}
            </span>
          ) : null}
          <div className="min-w-0 space-y-1.5">
            <CardTitle className="text-[17px] leading-[23px] font-[650] [overflow-wrap:anywhere]">
              {request.summary}
            </CardTitle>
            <CardDescription className="font-mono text-xs leading-4 font-[450]">
              {requestDescription(request, t)}
              <span className="text-muted-foreground"> · {suppliers.join(", ")}</span>
            </CardDescription>
            <ProposalExplanationBlock
              explanation={explanation}
              openDetails={!inspecting ? () => setInspecting(true) : undefined}
            />
            {why ? (
              <p data-slot="card-why" className="line-clamp-2 max-w-[80ch] text-sm text-muted-foreground" title={why}>
                <span className="font-medium text-foreground">{t("Why: ")}</span>
                {why}
              </p>
            ) : null}
          </div>
        </div>
        {request.lineCount === 0 ? (
          <p className="text-sm font-medium sm:max-w-64 sm:text-right">
            {checks.leftOut.length > 0
              ? t("Nothing could be ordered. Left out: {count}", { count: checks.leftOut.length })
              : t("Nothing could be ordered")}
          </p>
        ) : (
          <dl className="flex flex-wrap items-baseline gap-x-3 sm:block sm:text-right">
            <dt className="sr-only">{t("Total incl VAT")}</dt>
            <dd className="inline-block border-b-[3px] border-double border-foreground text-xl leading-7 font-bold tabular-nums">
              {inclVat !== null ? formatEur(inclVat) : inclVatText(request, t, formatEur)}
            </dd>
            <dt className="sr-only">{t("Total ex VAT")}</dt>
            <dd className="font-mono text-xs text-muted-foreground tabular-nums">
              {t("{amount} ex VAT", { amount: formatEur(request.totalExVat) })}
            </dd>
            {order?.deliveryFee != null ? (
              <>
                <dt className="sr-only">{t("Delivery fee")}</dt>
                <dd className="w-full font-mono text-xs text-muted-foreground tabular-nums">
                  {order.mov
                    ? t("Delivery fee {amount} (free from {threshold} ex VAT)", {
                        amount: formatEur(order.deliveryFee),
                        threshold: formatEur(order.mov.threshold),
                      })
                    : t("Delivery fee {amount}", { amount: formatEur(order.deliveryFee) })}
                </dd>
              </>
            ) : null}
            {/* Mock jury, 14 Nov: "€37.74" here and "Approve €62.74" below, with no sum between. */}
            {approveDiffers ? (
              <>
                <dt className="sr-only">{t("Amount you approve")}</dt>
                <dd className="w-full font-mono text-xs font-semibold tabular-nums">
                  {t("= {amount} to approve", { amount: formatEur(request.totalInclVat) })}
                </dd>
              </>
            ) : null}
          </dl>
        )}
      </CardHeader>
      <CardContent className="space-y-3 px-0">
        {chips.length > 0 ? (
          <ul className="flex flex-wrap gap-1.5" aria-label={t("Status")}>
            {chips.slice(0, CHIPS_SHOWN).map((chip) => (
              <li
                key={chip.key}
                className={cn(
                  "inline-flex items-center rounded-sm border px-1.5 py-px text-xs font-medium whitespace-nowrap",
                  TONE_CLASSES[chip.tone],
                )}
              >
                {t(chip.text, chip.values)}
              </li>
            ))}
          </ul>
        ) : null}
        {pending && cutoff ? (
          <p className={cn("break-words text-sm", cutoff.warning ? "hatch text-warning" : "text-muted-foreground")}>
            {cutoff.passed
              ? `${t("The cut-off has passed")}${cutoffOrigin}${cutoffEarliest}`
              : `${t("Approve before {time}", {
                  time: `${formatDate(cutoff.closingTime)} ${formatTime(cutoff.closingTime)}`,
                })}${cutoffOrigin}${cutoffEarliest}${cutoffTimeLeft ? ` · ${cutoffTimeLeft}` : ""}`}
          </p>
        ) : null}
        <RecallLines alerts={recalls} />
        {pending && stockMessage ? (
          <p id={stockBlockId} className="hatch text-sm text-warning">
            {stockMessage}
          </p>
        ) : null}
        <div id={inspectId} hidden={!inspecting} className="space-y-5 border-t pt-4">
          {inspecting ? (
            <>
              {pending && waitingNotice ? <p className="hatch text-sm text-warning">{waitingNotice}</p> : null}
              {editCount > 0 ? (
                <p className="text-sm text-muted-foreground">
                  {t("Changed by you: {count} edits. The Buyer learns from these.", { count: editCount })}
                </p>
              ) : null}
              {order ? (
                <section className="space-y-3" aria-label={t("Order lines")}>
                  {changeError ? (
                    <p role="alert" className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.danger)}>
                      {changeError}
                    </p>
                  ) : null}
                  <ProposalLines
                    lines={order.lines}
                    now={clock}
                    confirmBy="Valio"
                    checks={checks.perLine}
                    leftOut={checks.leftOut}
                    editing={
                      editing
                        ? {
                            busy,
                            value: quantityValue,
                            // A tapped chip and its note stay while the person corrects the number.
                            onType: (line, value) =>
                              setQuantities((current) => ({ ...current, [line.product.id]: value })),
                            onUpdate: (line) =>
                              void changeProposal({
                                type: "SET_QUANTITY",
                                productId: line.product.id,
                                quantity: Number(quantityValue(line)),
                                ...selectedChange(line.product.id),
                              }),
                            // Remove asks first: the chips and Remove line / Keep line show under the line.
                            // A second press closes the confirm, like Keep line.
                            onRemove: (line) =>
                              lineChanges[line.product.id]?.removing
                                ? resetLineChange(line.product.id)
                                : setLineChanges((current) => ({ ...current, [line.product.id]: { note: "", removing: true } })),
                            inputId: (line) => `qty-${request.id}-${line.product.id}`,
                            removeId,
                            removing: (line) => lineChanges[line.product.id]?.removing ?? false,
                            below: lineBelow,
                          }
                        : undefined
                    }
                  />
                  <MovProgress mov={order.mov} />
                  {editing ? (
                    <div className="space-y-3">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        aria-expanded={adding}
                        aria-controls={addId}
                        onClick={() => setAdding((shown) => !shown)}
                      >
                        <Plus aria-hidden />
                        {t("Add products")}
                      </Button>
                      <section id={addId} hidden={!adding} className="space-y-3" aria-label={t("Add products")}>
                        {adding ? (
                          <>
                            <label className="grid gap-1 text-sm font-medium" htmlFor={`product-search-${request.id}`}>
                              {t("Search products")}
                              <Input
                                id={`product-search-${request.id}`}
                                type="search"
                                value={search}
                                disabled={busy}
                                onChange={(event) => setSearch(event.target.value)}
                                placeholder={t("Search by name")}
                              />
                            </label>
                            {addables.status === "loading" ? (
                              <p className="text-sm text-muted-foreground">{t("Loading products…")}</p>
                            ) : null}
                            {addables.status === "error" ? (
                              <p role="alert" className="text-sm text-danger">
                                {addables.error.message}
                              </p>
                            ) : null}
                            {addables.status === "ready" ? (
                              addables.data.length === 0 ? (
                                <p className="text-sm text-muted-foreground">{t("No products found.")}</p>
                              ) : (
                                <ul className="divide-y divide-dashed divide-input">
                                  {addables.data.map((item) => (
                                    <AddableRow
                                      key={item.product.id}
                                      item={item}
                                      disabled={busy}
                                      onAdd={(quantity) =>
                                        void changeProposal({ type: "ADD_LINE", productId: item.product.id, quantity })
                                      }
                                    />
                                  ))}
                                </ul>
                              )
                            ) : null}
                          </>
                        ) : null}
                      </section>
                    </div>
                  ) : null}
                </section>
              ) : null}
              {pending && request.options?.length ? (
                <OptionCompare
                  options={request.options}
                  disabled={busy || !!approvalBlockedReason}
                  onChoose={onChooseOption ? chooseOption : undefined}
                  onApprove={() => setOpen("approve")}
                />
              ) : null}
              <section className="space-y-2">
                <h4 className="label-caps">{t("What to check")}</h4>
                <ul className="space-y-1.5">
                  {checks.general.map((r) => (
                    <li key={r.rule} className="border-l-[3px] border-warning py-0.5 pl-3 text-sm">
                      <div className="font-semibold">{translateReason(r.rule, t)}</div>
                      {r.detail ? <div className="text-foreground">{t(r.detail)}</div> : null}
                    </li>
                  ))}
                  {request.suppliersToConfirm.map((supplier) => (
                    <li
                      key={supplier.supplierId}
                      className="rounded-r-md border-l-[3px] border-warning bg-warning-surface px-3 py-2 text-sm text-warning"
                    >
                      {t("{supplier} must confirm stock. If you approve, the order is sent and waits for their confirmation: call or e-mail them.", {
                        supplier: supplier.name,
                      })}
                    </li>
                  ))}
                </ul>
              </section>
              <ModelTracePanel trace={request.modelTrace} />
            </>
          ) : null}
        </div>
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-2 border-t border-dashed border-input px-0 pt-3 [.border-t]:pt-3 sm:flex-row sm:items-center">
        <Button
          type="button"
          variant="ghost"
          className="w-full justify-between sm:mr-auto sm:w-auto"
          aria-expanded={inspecting}
          aria-controls={inspectId}
          onClick={() => setInspecting((shown) => !shown)}
        >
          {optionCount > 0 ? t("Inspect ({count} options)", { count: optionCount }) : t("Inspect")}
          <ChevronDown
            aria-hidden
            className={cn("motion-safe:transition-transform motion-safe:duration-150", inspecting && "rotate-180")}
          />
        </Button>
        {canDecide ? (
          <>
            {held ? (
              <p role="status" className="w-full text-sm text-muted-foreground sm:w-auto">
                {t("Blocked by a recall. This proposal cannot be approved as it is.")}
              </p>
            ) : null}
            {error && (
              <p role="alert" className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.danger)}>
                {error}
              </p>
            )}
            <Button variant="outline" className="w-full sm:w-auto" disabled={busy || !!approvalBlockedReason} onClick={() => setOpen("reject")}>
              <X aria-hidden />
              {t("Reject")}
            </Button>
            {pending ? (
              <Button
                className="w-full sm:w-auto"
                disabled={busy || !!stockMessage || !!approvalBlockedReason}
                aria-describedby={approveBlockDescription}
                onClick={() => setOpen("approve")}
              >
                <Check aria-hidden />
                {stockMessage || approvalBlockedReason
                  ? t("Approve")
                  : inclVat === null
                    ? t("Approve {amount}", { amount: formatEur(request.totalInclVat) })
                    : t("Approve {amount} incl VAT", { amount: formatEur(request.totalInclVat) })}
              </Button>
            ) : null}
          </>
        ) : (
          <p
            role="status"
            className={cn(
              "stamp-mark w-full text-sm font-medium sm:w-auto",
              status === "APPROVED" ? "text-success" : "text-muted-foreground",
            )}
          >
            {status === "APPROVED" ? (
              <span className="stamp text-lg" aria-hidden>
                {t("Approved")}
              </span>
            ) : null}
            {status === "APPROVED"
              ? t("Approved and recorded: {total} in all ({exVat} ex VAT). Nothing is sent to the supplier.", {
                  exVat: formatEur(request.totalExVat),
                  total: formatEur(request.totalInclVat),
                })
              : status === "IN_PROGRESS"
                ? t("In progress. This proposal cannot be approved yet.")
                : status === "BLOCKED_BY_RECALL"
                  ? t("Blocked by a recall. This proposal cannot be approved as it is.")
                  : t("Rejected. This order will not be sent.")}
          </p>
        )}
        {canDecide && approvalBlockedReason ? (
          <p id={accountBlockId} className="w-full text-sm text-muted-foreground">{approvalBlockedReason}</p>
        ) : null}
      </CardFooter>

      <Dialog open={open === "approve"} onOpenChange={(o) => setOpen(o ? "approve" : null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("Approve this order?")}</DialogTitle>
            <DialogDescription>
              {inclVat === null
                ? t("You approve exactly {exVat} ex VAT, {amount} in all ({total}). If the price or stock moves before it is placed, the gateway refuses it and asks again.", {
                    exVat: formatEur(request.totalExVat),
                    amount: formatEur(request.totalInclVat),
                    total: inclVatText(request, t, formatEur),
                  })
                : t("You approve exactly {exVat} ex VAT ({inclVat} incl VAT). If the price or stock moves before it is placed, the gateway refuses it and asks again.", {
                    exVat: formatEur(request.totalExVat),
                    inclVat: formatEur(request.totalInclVat),
                  })}
            </DialogDescription>
          </DialogHeader>
          {waitingNotice ? <p className="hatch text-sm text-warning">{waitingNotice}</p> : null}
          <DialogFooter>
            <Button
              disabled={busy || !!stockMessage || !!approvalBlockedReason}
              onClick={() =>
                decide("APPROVED", () =>
                  onApprove?.({
                    approvalId: request.id,
                    approvalRef: request.approvalRef,
                    expectedTotalExVat: request.totalExVat,
                    expectedTotalInclVat: request.totalInclVat,
                  }),
                )
              }
            >
              {t("Yes, approve {amount}", { amount: formatEur(request.totalInclVat) })}
            </Button>
            <DialogClose asChild>
              <Button variant="outline" disabled={busy}>
                {t("Cancel")}
              </Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={open === "reject"} onOpenChange={(o) => setOpen(o ? "reject" : null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("Reject this order?")}</DialogTitle>
            <DialogDescription>{t("This order will not be sent. Your reason goes in the audit log.")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor={reasonId}>{t("Reason (optional)")}</Label>
            <Textarea
              id={reasonId}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder={t("For example: 3 % fat is not right for the dessert menu")}
            />
          </div>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={busy || !!approvalBlockedReason}
              onClick={() => decide("REJECTED", () => onReject?.(request.id, reason.trim()))}
            >
              {t("Reject")}
            </Button>
            <DialogClose asChild>
              <Button variant="outline" disabled={busy}>
                {t("Cancel")}
              </Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function ChangeReasonChips({
  productName,
  disabled,
  reason,
  note,
  suggested,
  onReason,
  onNote,
}: {
  productName: string;
  disabled: boolean;
  reason?: ProposalChangeReason;
  note: string;
  suggested: ProposalChangeReason | null;
  onReason: (reason: ProposalChangeReason) => void;
  onNote: (note: string) => void;
}) {
  const t = useT();
  const noteId = useId();
  const counterId = useId();
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap gap-2" role="group" aria-label={t("Reason for changing {product}", { product: productName })}>
        {CHANGE_REASONS.map((option) => {
          const selected = reason === option.value;
          const showSuggestion = reason == null && suggested === option.value;
          return (
            <Button
              key={option.value}
              type="button"
              variant={selected ? "default" : "outline"}
              className={cn("min-h-11 rounded-full px-3", showSuggestion && "border-dashed")}
              aria-pressed={selected}
              aria-label={showSuggestion ? `${t(option.label)} · ${t("suggested")}` : undefined}
              disabled={disabled}
              onClick={() => onReason(option.value)}
            >
              {t(option.label)}
              {showSuggestion ? <span className="font-normal"> · {t("suggested")}</span> : null}
            </Button>
          );
        })}
      </div>
      {reason === "OTHER" ? (
        <div className="space-y-1">
          <Label htmlFor={noteId}>{t("Note (optional)")}</Label>
          <Textarea
            id={noteId}
            rows={2}
            maxLength={200}
            value={note}
            disabled={disabled}
            aria-describedby={counterId}
            onChange={(event) => onNote(event.target.value)}
          />
          <p id={counterId} className="text-xs text-muted-foreground">
            {t("{count}/200 characters", { count: note.length })}
          </p>
        </div>
      ) : null}
    </div>
  );
}

/** One product the person may add: one compact row, its quantity prefilled with the engine's suggestion. */
function AddableRow({
  item,
  disabled,
  onAdd,
}: {
  item: AddableProduct;
  disabled: boolean;
  onAdd: (quantity: number) => void;
}) {
  const t = useT();
  const [quantity, setQuantity] = useState(String(item.suggestedQuantity));
  const id = useId();
  return (
    <li className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-x-3 gap-y-1 py-2">
      <div className="flex min-w-0 items-center gap-2">
        <ProductThumb size="sm" en={item.product.names.en} fi={item.product.names.fi} brand={item.product.brand} />
        <div className="min-w-0">
          <div className="text-sm font-medium break-words">
            <ProductLink productId={item.product.id}>{item.product.names.en}</ProductLink>
          </div>
          <div className="font-mono text-[11px] leading-4 text-muted-foreground">
            {item.product.id} · {t("{amount} ex VAT", { amount: t(formatEur(item.offer.priceExVat)) })} ·{" "}
            {t("Stock on hand")}{" "}
            {item.onHand == null ? t("not counted") : t(formatStock(item.onHand, item.product.salesUnit))} · {t("On order")}{" "}
            {item.onOrder == null ? t("unknown") : `${formatNumber(item.onOrder)} ${peopleUnit(item.product.salesUnit, item.onOrder)}`}
          </div>
          <p className="text-xs text-muted-foreground">{item.why}</p>
        </div>
      </div>
      <form
        className="flex items-center gap-1"
        onSubmit={(event) => {
          event.preventDefault();
          if (Number.isInteger(Number(quantity)) && Number(quantity) >= 1) onAdd(Number(quantity));
        }}
      >
        <label className="sr-only" htmlFor={id}>
          {t("Quantity for {product} ({unit})", {
            product: item.product.names.en,
            unit: peopleUnit(item.product.salesUnit, Number(quantity)),
          })}
        </label>
        <Input
          id={id}
          type="number"
          min={1}
          step={1}
          value={quantity}
          disabled={disabled}
          onChange={(event) => setQuantity(event.target.value)}
          className="h-8 w-[4.5rem] px-2 text-right font-mono tabular-nums"
        />
        <span className="max-w-16 text-xs leading-4 text-muted-foreground">{peopleUnit(item.product.salesUnit, Number(quantity))}</span>
        <Button
          type="submit"
          size="sm"
          aria-label={t("Add {product}", { product: item.product.names.en })}
          disabled={disabled || !Number.isInteger(Number(quantity)) || Number(quantity) < 1}
        >
          {t("Add")}
        </Button>
      </form>
    </li>
  );
}
