import { Check, X } from "lucide-react";
import { useId, useState } from "react";

import { MovProgress } from "@/components/purchasing/mov-progress";
import { OptionCompare } from "@/components/purchasing/option-compare";
import { OrderLinesTable } from "@/components/purchasing/order-lines-table";
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
  formatOfferStock,
  formatStock,
  isPassed,
  isStockUnconfirmed,
} from "@/lib/format";
import { cn } from "@/lib/utils";
import { TONE_CLASSES } from "@/lib/tone";
import { useAsync } from "@/lib/use-async";
import type { AddableProduct, ApprovalRequest, Order, OrderLine, ProposalChange, RecallAlert } from "@/types";

/** What the gateway gets on approve: the exact totals the human read. */
export interface ApprovalDecision {
  approvalId: string;
  expectedTotalExVat: number;
  expectedTotalInclVat: number;
}

/**
 * One order outside the mandate, waiting for a human. Approve names the
 * exact total on the button and again in the confirmation, because that
 * figure is what the gateway checks (`expected_total`) when it places the
 * order. The human's "yes" to that figure is the consent; the total alone
 * is not.
 */
export function ApprovalCard({
  request,
  order,
  now = new Date(),
  onApprove,
  onReject,
  onChangeProposal,
  onChooseOption,
  listAddableProducts,
  editCount = 0,
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
  /** Recall alerts on this order; a blocked line still on it holds the approval. */
  recalls?: RecallAlert[];
}) {
  const [open, setOpen] = useState<"approve" | "reject" | null>(null);
  const [status, setStatus] = useState(request.status);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showOrder, setShowOrder] = useState(false);
  const [search, setSearch] = useState("");
  const [quantities, setQuantities] = useState<Record<string, string>>({});
  const addables = useAsync(() => listAddableProducts?.(search) ?? Promise.resolve([]), [search]);
  const reasonId = useId();
  const pending = status === "PENDING";
  const stockMessage =
    recallHold(recalls, order) ??
    (!order || order.lines.length === 0
      ? "Order details are unavailable. Reload them before approving."
      : order.lines.some((line) => isStockUnconfirmed(line.offer))
        ? "Waiting for supplier stock confirmation. You can review or reject this proposal; approval is available once stock is confirmed."
        : null);
  const editing = pending && onChangeProposal != null && listAddableProducts != null;

  async function changeProposal(change: ProposalChange) {
    if (!onChangeProposal) return;
    setBusy(true);
    setError(null);
    try {
      await onChangeProposal(change);
      addables.reload();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  function quantityValue(line: OrderLine) {
    return quantities[line.product.id] ?? String(line.quantity);
  }

  // The status changes only after the gateway confirms. If the call fails
  // (price moved, expected_total mismatch, network), the card stays PENDING
  // and shows the error, so nobody believes an order went through.
  async function decide(next: "APPROVED" | "REJECTED", call: () => void | Promise<void>) {
    if (next === "APPROVED" && stockMessage) return;
    setBusy(true);
    setError(null);
    try {
      await call();
      setStatus(next);
    } catch (e) {
      const what = next === "APPROVED" ? "Approval" : "Rejection";
      setError(`${what} failed: ${e instanceof Error ? e.message : String(e)}. The order is still pending.`);
    } finally {
      setBusy(false);
      setOpen(null);
    }
  }

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="leading-snug">{request.summary}</CardTitle>
        <CardDescription>
          {request.lineCount} {request.lineCount === 1 ? "line" : "lines"} · delivery {formatDate(request.deliveryDate)}{" "}
          · asked by {request.requestedBy}, {formatDateTime(request.createdAt)}
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-2 gap-3">
          <div>
            <dt className="text-xs text-muted-foreground">Total ex VAT</dt>
            <dd className="text-lg font-semibold tabular-nums">{formatEur(request.totalExVat)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Total incl VAT</dt>
            <dd className="text-lg font-semibold tabular-nums">{formatEur(request.totalInclVat)}</dd>
          </div>
        </dl>
        {editCount > 0 ? (
          <p className="text-sm text-muted-foreground">
            Changed by you: {editCount} edits. The Buyer learns from these.
          </p>
        ) : null}
        <section className="space-y-2">
          <h4 className="text-sm font-medium">What to check</h4>
          <ul className="space-y-2">
            {request.reasons.map((r) => (
              <li key={r.rule} className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.warning)}>
                <div className="font-medium">{r.rule}</div>
                <div className="text-foreground">{r.detail}</div>
              </li>
            ))}
          </ul>
        </section>
        <RecallLines alerts={recalls} />
        {pending && stockMessage ? (
          <p className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.warning)}>{stockMessage}</p>
        ) : null}
        {pending && request.options?.length ? (
          <OptionCompare
            options={request.options}
            disabled={busy}
            onChoose={onChooseOption}
            onApprove={() => setOpen("approve")}
          />
        ) : null}
        {order ? (
          <section className="space-y-3 border-t pt-4">
            <Button
              type="button"
              variant="outline"
              aria-expanded={showOrder}
              onClick={() => setShowOrder((shown) => !shown)}
            >
              {showOrder ? "Hide order lines" : "Show order lines"}
            </Button>
            {showOrder ? (
              <div className="space-y-4">
                {editing ? (
                  <ul className="divide-y">
                    {order.lines.map((line) => (
                      <li key={line.product.id} className="space-y-3 py-3">
                        <div>
                          <div className="font-medium">{line.product.names.en}</div>
                          <div className="text-xs text-muted-foreground">
                            {line.product.id} · {line.product.salesUnit}
                          </div>
                        </div>
                        <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
                          <dt className="text-muted-foreground">Stock</dt>
                          <dd>{formatOfferStock(line.offer)}</dd>
                          <dt className="text-muted-foreground">Cut-off</dt>
                          <dd>
                            {formatDateTime(line.offer.closingTime)}
                            {isPassed(line.offer.closingTime, now) ? " (passed)" : ""}
                          </dd>
                          <dt className="text-muted-foreground">Unit price</dt>
                          <dd>{formatEur(line.offer.priceExVat)} ex VAT</dd>
                        </dl>
                        <p className="text-sm text-muted-foreground">Why: {line.why}</p>
                        <div className="flex items-end gap-2">
                          <label
                            className="grid min-w-0 flex-1 gap-1 text-sm font-medium"
                            htmlFor={`qty-${request.id}-${line.product.id}`}
                          >
                            Quantity for {line.product.names.en} ({line.product.salesUnit})
                            <Input
                              id={`qty-${request.id}-${line.product.id}`}
                              type="number"
                              min={1}
                              step={1}
                              value={quantityValue(line)}
                              disabled={busy}
                              onChange={(event) =>
                                setQuantities((current) => ({ ...current, [line.product.id]: event.target.value }))
                              }
                            />
                          </label>
                          <Button
                            type="button"
                            variant="outline"
                            disabled={busy || Number(quantityValue(line)) === line.quantity}
                            aria-label={`Update ${line.product.names.en}`}
                            onClick={() =>
                              void changeProposal({
                                type: "SET_QUANTITY",
                                productId: line.product.id,
                                quantity: Number(quantityValue(line)),
                              })
                            }
                          >
                            Update
                          </Button>
                          <Button
                            type="button"
                            variant="destructive"
                            disabled={busy}
                            aria-label={`Remove ${line.product.names.en}`}
                            onClick={() => void changeProposal({ type: "REMOVE_LINE", productId: line.product.id })}
                          >
                            Remove
                          </Button>
                        </div>
                      </li>
                    ))}
                  </ul>
                ) : (
                  <OrderLinesTable lines={order.lines} now={now} />
                )}
                {editing ? (
                  <section className="space-y-3 border-t pt-4" aria-labelledby={`add-products-${request.id}`}>
                    <h4 id={`add-products-${request.id}`} className="font-medium">
                      Add products
                    </h4>
                    <label className="grid gap-1 text-sm font-medium" htmlFor={`product-search-${request.id}`}>
                      Search products
                      <Input
                        id={`product-search-${request.id}`}
                        type="search"
                        value={search}
                        disabled={busy}
                        onChange={(event) => setSearch(event.target.value)}
                        placeholder="Search by name"
                      />
                    </label>
                    {addables.status === "loading" ? (
                      <p className="text-sm text-muted-foreground">Loading products…</p>
                    ) : null}
                    {addables.status === "error" ? (
                      <p role="alert" className="text-sm text-danger">
                        {addables.error.message}
                      </p>
                    ) : null}
                    {addables.status === "ready" ? (
                      addables.data.length === 0 ? (
                        <p className="text-sm text-muted-foreground">No products found.</p>
                      ) : (
                        <ul className="divide-y">
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
                  </section>
                ) : null}
                <MovProgress mov={order.mov} />
              </div>
            ) : null}
          </section>
        ) : null}
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-2 sm:flex-row sm:justify-end">
        {pending ? (
          <>
            {error && (
              <p role="alert" className={cn("rounded-md border px-3 py-2 text-sm sm:mr-auto", TONE_CLASSES.danger)}>
                {error}
              </p>
            )}
            <Button variant="outline" disabled={busy} onClick={() => setOpen("reject")}>
              <X aria-hidden />
              Reject
            </Button>
            <Button disabled={busy || !!stockMessage} onClick={() => setOpen("approve")}>
              <Check aria-hidden />
              Approve {formatEur(request.totalInclVat)} incl VAT
            </Button>
          </>
        ) : (
          <p
            role="status"
            className={cn(
              "rounded-md border px-3 py-2 text-sm font-medium",
              status === "APPROVED" ? TONE_CLASSES.success : TONE_CLASSES.neutral,
            )}
          >
            {status === "APPROVED"
              ? `Approved: ${formatEur(request.totalExVat)} ex VAT, ${formatEur(request.totalInclVat)} incl VAT. The order may now be sent.`
              : "Rejected. This order will not be sent."}
          </p>
        )}
      </CardFooter>

      <Dialog open={open === "approve"} onOpenChange={(o) => setOpen(o ? "approve" : null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Approve this order?</DialogTitle>
            <DialogDescription>
              You approve exactly {formatEur(request.totalExVat)} ex VAT ({formatEur(request.totalInclVat)} incl VAT).
              If the price or stock moves before it is placed, the gateway refuses it and asks again.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              disabled={busy || !!stockMessage}
              onClick={() =>
                decide("APPROVED", () =>
                  onApprove?.({
                    approvalId: request.id,
                    expectedTotalExVat: request.totalExVat,
                    expectedTotalInclVat: request.totalInclVat,
                  }),
                )
              }
            >
              Yes, approve {formatEur(request.totalInclVat)}
            </Button>
            <DialogClose asChild>
              <Button variant="outline" disabled={busy}>
                Cancel
              </Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={open === "reject"} onOpenChange={(o) => setOpen(o ? "reject" : null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Reject this order?</DialogTitle>
            <DialogDescription>This order will not be sent. Your reason goes in the audit log.</DialogDescription>
          </DialogHeader>
          <div className="space-y-2">
            <Label htmlFor={reasonId}>Reason (optional)</Label>
            <Textarea
              id={reasonId}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              placeholder="For example: 3 % fat is not right for the dessert menu"
            />
          </div>
          <DialogFooter>
            <Button
              variant="destructive"
              disabled={busy}
              onClick={() => decide("REJECTED", () => onReject?.(request.id, reason.trim()))}
            >
              Reject
            </Button>
            <DialogClose asChild>
              <Button variant="outline" disabled={busy}>
                Cancel
              </Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

function AddableRow({
  item,
  disabled,
  onAdd,
}: {
  item: AddableProduct;
  disabled: boolean;
  onAdd: (quantity: number) => void;
}) {
  const [quantity, setQuantity] = useState(String(item.suggestedQuantity));
  const id = useId();
  return (
    <li className="space-y-2 py-3">
      <div className="font-medium">{item.product.names.en}</div>
      <div className="text-xs text-muted-foreground">
        {item.product.id} · {item.product.salesUnit}
      </div>
      <dl className="grid grid-cols-2 gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted-foreground">Stock on hand</dt>
        <dd>{item.onHand == null ? "not counted" : formatStock(item.onHand, item.product.salesUnit)}</dd>
        <dt className="text-muted-foreground">On order</dt>
        <dd>{item.onOrder == null ? "unknown" : `${formatNumber(item.onOrder)} ${item.product.salesUnit}`}</dd>
        <dt className="text-muted-foreground">Price</dt>
        <dd>{formatEur(item.offer.priceExVat)} ex VAT</dd>
      </dl>
      <p className="text-sm text-muted-foreground">{item.why}</p>
      <div className="flex items-end gap-2">
        <label className="grid min-w-0 flex-1 gap-1 text-sm font-medium" htmlFor={id}>
          Quantity for {item.product.names.en} ({item.product.salesUnit})
          <Input
            id={id}
            type="number"
            min={1}
            step={1}
            value={quantity}
            disabled={disabled}
            onChange={(event) => setQuantity(event.target.value)}
          />
        </label>
        <Button
          type="button"
          aria-label={`Add ${item.product.names.en}`}
          disabled={disabled || !Number.isInteger(Number(quantity)) || Number(quantity) < 1}
          onClick={() => onAdd(Number(quantity))}
        >
          Add
        </Button>
      </div>
    </li>
  );
}
