import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";

import type { Api } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/format";
import { auditActorForRole, useRole } from "@/lib/role";
import { useSession } from "@/lib/session";
import { useAsync } from "@/lib/use-async";
import type { SupplierOffer } from "@/types";

/** Who chose the product, in words a person reads. The value itself comes from the supplier. */
export function madeByLabel(madeBy: string): string {
  const value = madeBy.trim();
  if (/^nemotron/i.test(value)) return "Nemotron 3.5 Super VL";
  if (value.toLowerCase() === "rule") return "picked by rule, not by a model";
  return value || "unknown";
}

function supplierName(offer: SupplierOffer): string {
  return /valio/i.test(offer.supplierId) ? "Valio Aimo" : "a supplier";
}

/**
 * A supplier's suggestion (docs/contract.md, "Supplier offers"): shown only while an offer is
 * open. "Make a proposal" makes a normal proposal that still waits for approval; nothing is
 * ordered here. The tile is an extra: when the list cannot be read, Home stays as it is.
 */
export function SupplierOfferTile({ api }: { api: Api }) {
  const state = useAsync(() => api.listSupplierOffers(), [api]);
  const { role } = useRole();
  const { session } = useSession();
  const navigate = useNavigate();
  const [pending, setPending] = useState<"accept" | "decline" | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [hidden, setHidden] = useState<string[]>([]);

  const offer =
    state.status === "ready" ? state.data.find((row) => row.status === "OPEN" && !hidden.includes(row.id)) : undefined;
  if (!offer) return null;

  const blocked = session && !session.canApprove ? "Your account cannot accept or decline offers." : null;
  const actor = auditActorForRole(role);
  const product = offer.productName ?? `product ${offer.productId}`;
  const replaced = offer.replacesProductName ?? `product ${offer.replacesProductId}`;

  const act = async (kind: "accept" | "decline") => {
    setPending(kind);
    setMessage(null);
    try {
      if (kind === "decline") {
        await api.declineSupplierOffer(offer.id, actor);
        setHidden((ids) => [...ids, offer.id]);
        return;
      }
      const accepted = await api.acceptSupplierOffer(offer.id, actor);
      if (accepted.proposalStatus === "REJECTED") {
        setMessage(
          `${supplierName(offer)} cannot deliver ${product} for ${formatDate(offer.requestedDate)} after all. No proposal was made.`,
        );
        return;
      }
      await navigate({ to: "/approvals" });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "That did not work. Try again.");
    } finally {
      setPending(null);
    }
  };

  return (
    <Card className="md:col-span-2" aria-labelledby="supplier-offer-title">
      <CardHeader>
        <CardTitle id="supplier-offer-title" className="label-caps leading-4">
          Offer from {supplierName(offer)}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <p className="break-words text-base font-semibold">{product}</p>
          <p className="break-words text-sm">
            in place of {replaced}, which is predicted short on{" "}
            <time dateTime={offer.requestedDate}>{formatDate(offer.requestedDate)}</time>
          </p>
          <p className="font-mono text-[13px] tabular-nums text-muted-foreground">
            {offer.quantity} {offer.unit}, from your own forecast
          </p>
        </div>
        <figure className="space-y-1 border-l-2 border-border pl-3">
          <blockquote className="whitespace-pre-line break-words text-sm">{offer.reason || "No reason given."}</blockquote>
          <figcaption className="text-xs text-muted-foreground">
            written by {supplierName(offer) === "Valio Aimo" ? "Valio's" : "the supplier's"} selling agent (
            {madeByLabel(offer.madeBy)})
          </figcaption>
        </figure>
        {!offer.allergenDataKnown && (
          <p className="break-words text-sm font-medium">
            The catalog has no allergen data for this product. Check the label before you approve.
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          This is a suggestion, not an order. A proposal still waits for your approval, with the live price.
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            className="w-full sm:w-auto"
            disabled={pending !== null || blocked !== null}
            onClick={() => void act("accept")}
          >
            {pending === "accept" ? "Making the proposal…" : "Make a proposal"}
          </Button>
          <Button
            variant="outline"
            className="w-full sm:w-auto"
            disabled={pending !== null || blocked !== null}
            onClick={() => void act("decline")}
          >
            No thanks
          </Button>
        </div>
        <p className="text-sm" role="status" aria-live="polite">
          {message ?? blocked ?? ""}
        </p>
      </CardContent>
    </Card>
  );
}
