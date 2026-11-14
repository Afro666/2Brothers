import { useState } from "react";
import { useNavigate } from "@tanstack/react-router";

import type { Api } from "@/api/types";
import { Button } from "@/components/ui/button";
import { ProductThumb } from "@/components/purchasing/product-thumb";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { formatDate } from "@/lib/format";
import { useT } from "@/lib/i18n";
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
  const t = useT();
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

  const blocked = session && !session.canApprove ? t("Your account cannot accept or decline offers.") : null;
  const actor = auditActorForRole(role);
  const product = offer.productName ?? t("product {id}", { id: offer.productId });
  const replaced = offer.replacesProductName ?? t("product {id}", { id: offer.replacesProductId });

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
          t("{supplier} cannot deliver {product} for {date} after all. No proposal was made.", {
            supplier: supplierName(offer),
            product,
            date: formatDate(offer.requestedDate),
          }),
        );
        return;
      }
      await navigate({ to: "/approvals" });
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t("That did not work. Try again."));
    } finally {
      setPending(null);
    }
  };

  return (
    <Card className="md:col-span-2" aria-labelledby="supplier-offer-title">
      <CardHeader>
        <CardTitle id="supplier-offer-title" className="label-caps leading-4">
          {t("Offer from {supplier}", { supplier: t(supplierName(offer)) })}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-1">
          <div className="flex items-center gap-3">
            <ProductThumb en={offer.productName} />
            <p className="min-w-0 break-words text-base font-semibold">{product}</p>
          </div>
          <p className="break-words text-sm">
            {t("in place of {product}, which is predicted short on", { product: replaced })}{" "}
            <time dateTime={offer.requestedDate}>{formatDate(offer.requestedDate)}</time>
          </p>
          <p className="font-mono text-[13px] tabular-nums text-muted-foreground">
            {t("{quantity} {unit}, from your own forecast", { quantity: offer.quantity, unit: offer.unit })}
          </p>
        </div>
        <figure className="space-y-1 border-l-2 border-border pl-3">
          <blockquote className="whitespace-pre-line break-words text-sm">
            {offer.reason || t("No reason given.")}
          </blockquote>
          <figcaption className="text-xs text-muted-foreground">
            {t("written by {possessive} selling agent ({madeBy})", {
              possessive: t(supplierName(offer) === "Valio Aimo" ? "Valio's" : "the supplier's"),
              madeBy: t(madeByLabel(offer.madeBy)),
            })}
          </figcaption>
        </figure>
        {!offer.allergenDataKnown && (
          <p className="break-words text-sm font-medium">
            {t("The catalog has no allergen data for this product. Check the label before you approve.")}
          </p>
        )}
        <p className="text-sm text-muted-foreground">
          {t("This is a suggestion, not an order. A proposal still waits for your approval, with the live price.")}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button
            className="w-full sm:w-auto"
            disabled={pending !== null || blocked !== null}
            onClick={() => void act("accept")}
          >
            {pending === "accept" ? t("Making the proposal…") : t("Make a proposal")}
          </Button>
          <Button
            variant="outline"
            className="w-full sm:w-auto"
            disabled={pending !== null || blocked !== null}
            onClick={() => void act("decline")}
          >
            {t("No thanks")}
          </Button>
        </div>
        <p className="text-sm" role="status" aria-live="polite">
          {message ?? blocked ?? ""}
        </p>
      </CardContent>
    </Card>
  );
}
