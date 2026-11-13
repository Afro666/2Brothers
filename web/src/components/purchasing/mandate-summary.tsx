import { Check, UserCheck } from "lucide-react";
import type { ReactNode } from "react";

import { formatDate, formatEur } from "@/lib/format";
import type { Mandate } from "@/types";

import { AllergenChip, LabelChip } from "./chips";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-medium">{title}</h4>
      {children}
    </section>
  );
}

/** What the agent may do on its own. Anything outside it goes to a human. */
export function MandateSummary({ mandate }: { mandate: Mandate }) {
  const weekLeft = Math.max(0, mandate.weeklyLimitExVat - mandate.spentThisWeekExVat);
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">
        {mandate.restaurant} · signed by {mandate.signedBy} · valid until {formatDate(mandate.validUntil)} ·{" "}
        {mandate.id}
      </p>

      <Section title="Spend limits (ex VAT)">
        <dl className="grid grid-cols-1 gap-3 sm:grid-cols-3">
          <div>
            <dt className="text-xs text-muted-foreground">Auto-approve per order</dt>
            <dd className="font-semibold tabular-nums">up to {formatEur(mandate.autoApproveLimitExVat)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Per week</dt>
            <dd className="font-semibold tabular-nums">{formatEur(mandate.weeklyLimitExVat)}</dd>
          </div>
          <div>
            <dt className="text-xs text-muted-foreground">Left this week</dt>
            <dd className="font-semibold tabular-nums">{formatEur(weekLeft)}</dd>
          </div>
        </dl>
      </Section>

      <Section title="Excluded allergens (refused, even as may contain)">
        <div className="flex flex-wrap gap-1">
          {mandate.excludedAllergens.map((a) => (
            <AllergenChip key={a.code} allergen={a} />
          ))}
        </div>
        <p className="text-xs text-muted-foreground">
          A product with missing allergen data needs a human: unknown is not allergen-free.
        </p>
      </Section>

      <Section title="Accepted labels">
        <div className="flex flex-wrap gap-1">
          {mandate.acceptedLabels.map((l) => (
            <LabelChip key={l} label={l} />
          ))}
        </div>
      </Section>

      <Section title="Substitution rules">
        <ul className="space-y-1.5 text-sm">
          {mandate.substitutionRules.map((r) => (
            <li key={r.rule} className="flex items-start gap-2">
              {r.needsApproval ? (
                <UserCheck className="mt-0.5 size-4 shrink-0 text-warning" aria-hidden />
              ) : (
                <Check className="mt-0.5 size-4 shrink-0 text-success" aria-hidden />
              )}
              <span>
                {r.rule}
                <span className="text-muted-foreground">
                  {r.needsApproval ? " (needs approval)" : " (agent may do this)"}
                </span>
              </span>
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}
