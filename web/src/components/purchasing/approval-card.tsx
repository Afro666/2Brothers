import { Check, X } from "lucide-react";
import { useId, useState } from "react";

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
import { Textarea } from "@/components/ui/textarea";
import { formatDate, formatDateTime, formatEur } from "@/lib/format";
import { cn } from "@/lib/utils";
import { TONE_CLASSES } from "@/lib/tone";
import type { ApprovalRequest } from "@/types";

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
  onApprove,
  onReject,
}: {
  request: ApprovalRequest;
  onApprove?: (decision: ApprovalDecision) => void;
  onReject?: (approvalId: string, reason: string) => void;
}) {
  const [open, setOpen] = useState<"approve" | "reject" | null>(null);
  const [status, setStatus] = useState(request.status);
  const [reason, setReason] = useState("");
  const reasonId = useId();
  const pending = status === "PENDING";

  return (
    <Card className="gap-4">
      <CardHeader>
        <CardTitle className="leading-snug">{request.summary}</CardTitle>
        <CardDescription>
          {request.lineCount} {request.lineCount === 1 ? "line" : "lines"} · delivery {formatDate(request.deliveryDate)} ·
          asked by {request.requestedBy}, {formatDateTime(request.createdAt)}
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
        <section className="space-y-2">
          <h4 className="text-sm font-medium">Why it needs you</h4>
          <ul className="space-y-2">
            {request.reasons.map((r) => (
              <li key={r.rule} className={cn("rounded-md border px-3 py-2 text-sm", TONE_CLASSES.warning)}>
                <div className="font-medium">{r.rule}</div>
                <div className="text-foreground">{r.detail}</div>
              </li>
            ))}
          </ul>
        </section>
      </CardContent>
      <CardFooter className="flex-col items-stretch gap-2 sm:flex-row sm:justify-end">
        {pending ? (
          <>
            <Button variant="outline" onClick={() => setOpen("reject")}>
              <X aria-hidden />
              Reject
            </Button>
            <Button onClick={() => setOpen("approve")}>
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
              ? `Approved: ${formatEur(request.totalExVat)} ex VAT, ${formatEur(request.totalInclVat)} incl VAT. The agent may now place it.`
              : "Rejected. The agent will not place this order."}
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
              onClick={() => {
                setStatus("APPROVED");
                setOpen(null);
                onApprove?.({
                  approvalId: request.id,
                  expectedTotalExVat: request.totalExVat,
                  expectedTotalInclVat: request.totalInclVat,
                });
              }}
            >
              Yes, approve {formatEur(request.totalInclVat)}
            </Button>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={open === "reject"} onOpenChange={(o) => setOpen(o ? "reject" : null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Reject this order?</DialogTitle>
            <DialogDescription>The agent will not place it. Your reason goes in the audit log.</DialogDescription>
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
              onClick={() => {
                setStatus("REJECTED");
                setOpen(null);
                onReject?.(request.id, reason.trim());
              }}
            >
              Reject
            </Button>
            <DialogClose asChild>
              <Button variant="outline">Cancel</Button>
            </DialogClose>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}
