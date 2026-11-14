import { ArrowRight } from "lucide-react";

import { NemotronMark } from "@/components/nemotron-mark";
import { useT } from "@/lib/i18n";

/**
 * Who decides what on every order: the model picks products, the engine sets quantities,
 * a person signs. Machines are dashed boxes and the person is solid ink, as in the activity log.
 */
export function DecisionStrip() {
  const t = useT();
  const steps = [
    { actor: t("Buyer agent"), machine: true, does: t("chooses the products"), by: "Nemotron 3.5 Super VL" },
    { actor: t("Ordering engine"), machine: true, does: t("sets the quantities"), by: t("fixed rules, no model") },
    { actor: t("You"), machine: false, does: t("approve the exact total"), by: t("nothing is sent before that") },
  ];
  return (
    <section aria-label={t("Who decides what")} className="space-y-2">
      <h3 className="label-caps">{t("Who decides what")}</h3>
      <ol className="grid gap-x-3 gap-y-3 sm:grid-cols-[1fr_auto_1fr_auto_1fr] sm:items-start">
        {steps.map((step, index) => (
          <li key={step.actor} className="contents">
            <div className="min-w-0 text-sm">
              <span className="actor-box" data-actor={step.machine ? "machine" : "person"}>
                {step.actor}
              </span>{" "}
              <span className="font-medium">{step.does}</span>
              <p className="mt-0.5 font-mono text-xs text-muted-foreground">
                {index === 0 ? <NemotronMark /> : null}
                {step.by}
              </p>
            </div>
            {index < steps.length - 1 ? (
              <ArrowRight aria-hidden className="mt-0.5 hidden size-4 text-muted-foreground sm:block" />
            ) : null}
          </li>
        ))}
      </ol>
    </section>
  );
}
