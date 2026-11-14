import { useOptionalApi } from "@/api";
import type { ProposalExplanation } from "@/api/types";
import { useT } from "@/lib/i18n";
import { useProposalExplanation } from "@/lib/proposal-explanation";

/**
 * "Written by" needs a readable model name: `nemotron-3.5-super-vl` is written
 * "Nemotron 3.5 Super VL". An unknown shape is shown as sent.
 */
export function explanationModelName(model: string): string {
  const known = /^nemotron-(\d+(?:\.\d+)*)-super-vl$/i.exec(model);
  if (!known) return model;
  return `Nemotron ${known[1]} Super VL`;
}

/**
 * The checked Nemotron explanation, in its own small hook so both approval cards share it
 * (#1173). Without an ApiProvider (a card rendered on its own) it asks nothing and shows nothing.
 */
export function useCardExplanation(proposalId: string | null | undefined, enabled: boolean, source: unknown) {
  const api = useOptionalApi();
  return useProposalExplanation(api, proposalId, enabled, source);
}

/**
 * A short model explanation above the totals. Model text is rendered as text, never as HTML.
 * With no explanation it renders nothing at all: no placeholder, no spinner, no reserved space.
 */
export function ProposalExplanationBlock({
  explanation,
  openDetails,
}: {
  explanation: ProposalExplanation | null;
  /** Opens the card's rule-based decision record; absent when the card has none on screen. */
  openDetails?: () => void;
}) {
  const t = useT();
  if (!explanation?.text) return null;
  return (
    <section
      aria-label={t("Short explanation")}
      className="space-y-2 rounded-md border border-dashed border-input bg-muted/40 px-3 py-2.5"
    >
      <p data-proposal-explanation className="text-sm leading-5 whitespace-pre-line">
        {explanation.text}
      </p>
      <p className="text-xs leading-4 text-muted-foreground">
        {t("Written by {model} from the checked decision record", {
          model: explanationModelName(explanation.model) || "Nemotron 3.5 Super VL",
        })}
      </p>
      {openDetails ? (
        <button
          type="button"
          className="text-xs font-medium underline underline-offset-2 outline-none hover:no-underline focus-visible:ring-[3px] focus-visible:ring-ring/70"
          onClick={openDetails}
        >
          {t("Open the full decision record")}
        </button>
      ) : null}
    </section>
  );
}
