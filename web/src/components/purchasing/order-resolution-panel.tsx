import { Check, X } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";

import { ApiError, useApi } from "@/api";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { OrderLinesTable } from "@/components/purchasing/order-lines-table";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { formatDateTime, formatEur } from "@/lib/format";
import { TONE_CLASSES } from "@/lib/tone";
import { cn } from "@/lib/utils";
import { useAsync } from "@/lib/use-async";
import type { Order, OrderResolutionResult } from "@/types";

function plainMessage(error: Error, action: "placed" | "not_sent" | null = null): string {
  if (!(error instanceof ApiError)) return error.message;
  if (error.code === "HUMAN_SESSION_REQUIRED") {
    return "Only a signed-in person can check or resolve this order. Nothing was sent.";
  }
  if (error.code === "ROLE_REQUIRED") {
    return "Your role cannot resolve orders. Ask an approver to check with the supplier.";
  }
  if (error.code === "ALREADY_RESOLVED") {
    return "Someone else already resolved this order another way. Reloading the latest details.";
  }
  if (error.code === "ORDER_NOT_RESOLVABLE") {
    return "This order is no longer waiting for resolution. Reloading the latest details.";
  }
  if (error.code === "INVALID_REQUEST") {
    return action === "not_sent"
      ? "The note must be at most 500 characters. Nothing was recorded."
      : "Enter the supplier's order reference (1 to 200 characters). Nothing was recorded.";
  }
  return error.message;
}

export function OrderResolutionPanel({ order, onChanged }: { order: Order; onChanged: () => void }) {
  const api = useApi();
  const state = useAsync(async () => {
    const session = await api.getCurrentSession();
    const resolution = session.kind === "human" && session.canApprove ? await api.getOrderResolution(order.id) : null;
    return { session, resolution };
  }, [api, order.id]);
  const [open, setOpen] = useState<"placed" | "not_sent" | null>(null);
  const [reference, setReference] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [permissionDenied, setPermissionDenied] = useState(false);
  const [latest, setLatest] = useState<OrderResolutionResult | null>(null);

  async function resolve() {
    if (!open || state.status !== "ready" || !state.data.session.name) return;
    const trimmedReference = reference.trim();
    const trimmedNote = note.trim();
    if (open === "placed" && (!trimmedReference || trimmedReference.length > 200)) {
      setError("Enter the supplier's order reference (1 to 200 characters).");
      return;
    }
    if (open === "not_sent" && trimmedNote.length > 500) {
      setError("The note must be at most 500 characters.");
      return;
    }
    const action = open;
    setBusy(true);
    setError(null);
    try {
      const result = await api.resolveOrder(
        order.id,
        action === "placed"
          ? { resolution: "placed", supplierOrderRef: trimmedReference }
          : { resolution: "not_sent", note: trimmedNote },
        state.data.session.name,
      );
      setLatest(result);
      setOpen(null);
      toast.success(action === "placed" ? "Order marked as placed." : "Order marked as not sent.");
      onChanged();
    } catch (caught) {
      const nextError = caught instanceof Error ? caught : new Error(String(caught));
      setError(plainMessage(nextError, action));
      if (nextError instanceof ApiError) {
        if (nextError.code === "HUMAN_SESSION_REQUIRED" || nextError.code === "ROLE_REQUIRED") {
          setPermissionDenied(true);
          setOpen(null);
        }
        if (nextError.code === "ALREADY_RESOLVED" || nextError.code === "ORDER_NOT_RESOLVABLE") {
          setOpen(null);
          state.reload();
          onChanged();
        }
      }
    } finally {
      setBusy(false);
    }
  }

  const known = state.status === "ready" ? state.data.resolution : null;
  const session = state.status === "ready" ? state.data.session : null;
  const record = latest?.resolution ?? known?.resolution ?? null;
  const expectedTotal = known ? known.expectedTotal : order.totalInclVat;
  const lines = known ? known.lines : order.lines;
  const supplierStatus = latest ? latest.status : known?.status ?? null;
  const outcome = latest?.outcome ?? known?.outcome ?? null;
  const canResolve =
    known?.resolvable === true &&
    session?.kind === "human" &&
    session.canApprove &&
    session.name != null &&
    !permissionDenied &&
    !record;

  return (
    <Card aria-labelledby="unknown-send-title">
      <CardHeader>
        <h2 id="unknown-send-title" className="leading-none font-semibold">
          {record ? "Resolution recorded" : "Check this order with the supplier"}
        </h2>
        <CardDescription>
          The app cannot ask the supplier whether this order arrived. Check by phone, e-mail or the supplier's portal,
          then record what happened. Neither choice resends the order.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-5">
        {state.status === "loading" ? <LoadingState label="Loading resolution details" /> : null}
        {state.status === "error" ? (
          <ErrorState message={plainMessage(state.error)} onRetry={state.reload} />
        ) : null}
        {state.status === "ready" ? (
          <>
            <dl className="grid gap-x-6 gap-y-3 text-sm sm:grid-cols-2">
              <div>
                <dt className="text-muted-foreground">Expected total incl VAT</dt>
                <dd className="font-medium tabular-nums">{formatEur(expectedTotal)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Gateway outcome</dt>
                <dd>{outcome ?? "unknown"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Supplier status</dt>
                <dd>{supplierStatus ?? "unknown"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Approved by</dt>
                <dd>{known?.approvedBy ?? "unknown"}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Approved at</dt>
                <dd>{formatDateTime(known?.createdAt ?? null)}</dd>
              </div>
              <div>
                <dt className="text-muted-foreground">Approval idempotency key</dt>
                <dd className="break-all">{known?.idempotencyKey ?? "unknown"}</dd>
              </div>
              {record ? (
                <>
                  <div>
                    <dt className="text-muted-foreground">Recorded by</dt>
                    <dd>{record.resolvedBy ?? "unknown"}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Recorded at</dt>
                    <dd>{formatDateTime(record.resolvedAt)}</dd>
                  </div>
                  <div>
                    <dt className="text-muted-foreground">Supplier order reference</dt>
                    <dd className="break-all">{record.supplierOrderRef ?? "unknown"}</dd>
                  </div>
                </>
              ) : null}
            </dl>
            <section aria-label="Lines known for this order">
              <OrderLinesTable lines={lines} now={new Date()} />
            </section>
            {record ? (
              <p role="status" className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.success)}>
                {record.resolution === "placed"
                  ? `Marked as placed (${record.resolvedBy ?? "unknown"}).`
                  : "Marked as NOT_SENT. The proposal is back in the approval inbox."}
                {record.note ? ` Note: ${record.note}` : ""}
              </p>
            ) : null}
            {session && (!session.canApprove || session.kind !== "human") ? (
              <p role="alert" className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.warning)}>
                {session.kind === "human"
                  ? "Your role cannot resolve orders. Ask an approver to check with the supplier."
                  : "Only a signed-in person can resolve this order."}
              </p>
            ) : null}
            {permissionDenied || (error && !open) ? (
              <p role="alert" className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.danger)}>
                {error}
              </p>
            ) : null}
            {canResolve ? (
              <div className="flex flex-col gap-2 sm:flex-row">
                <Button type="button" onClick={() => { setError(null); setOpen("placed"); }}>
                  <Check aria-hidden />
                  It was placed
                </Button>
                <Button type="button" variant="outline" onClick={() => { setError(null); setOpen("not_sent"); }}>
                  <X aria-hidden />
                  It was not sent
                </Button>
              </div>
            ) : null}
          </>
        ) : null}
      </CardContent>

      <Dialog open={open !== null} onOpenChange={(isOpen) => { if (!isOpen && !busy) setOpen(null); }}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{open === "placed" ? "Confirm it was placed" : "Confirm it was not sent"}</DialogTitle>
            <DialogDescription>
              {open === "placed"
                ? "Record the reference you checked with the supplier. This does not place or resend the order."
                : "Record that the supplier has no order. The proposal returns to the approval inbox; nothing is resent."}
            </DialogDescription>
          </DialogHeader>
          <form
            className="flex min-h-0 flex-col gap-4"
            onSubmit={(event) => {
              event.preventDefault();
              void resolve();
            }}
          >
            <DialogBody className="space-y-2">
              {open === "placed" ? (
                <>
                  <Label htmlFor="supplier-order-ref">Supplier order reference</Label>
                  <Input
                    id="supplier-order-ref"
                    value={reference}
                    onChange={(event) => setReference(event.target.value)}
                    required
                    minLength={1}
                    maxLength={200}
                    autoComplete="off"
                    disabled={busy}
                  />
                </>
              ) : (
                <>
                  <Label htmlFor="resolution-note">Note (optional)</Label>
                  <Textarea
                    id="resolution-note"
                    value={note}
                    onChange={(event) => setNote(event.target.value)}
                    maxLength={500}
                    disabled={busy}
                    placeholder="For example: Valio sales desk has no such order"
                  />
                </>
              )}
              {error && open ? (
                <p role="alert" className="text-sm text-danger">
                  {error}
                </p>
              ) : null}
            </DialogBody>
            <DialogFooter>
              <Button type="submit" disabled={busy}>
                {busy ? "Recording…" : open === "placed" ? "Confirm placed" : "Confirm not sent"}
              </Button>
              <DialogClose asChild>
                <Button type="button" variant="outline" disabled={busy}>
                  Cancel
                </Button>
              </DialogClose>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
