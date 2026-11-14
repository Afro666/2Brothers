import { useEffect, useRef, useState } from "react";

import type { Api, ProposalExplanation } from "@/api/types";
import { useLanguage } from "@/lib/i18n";

/** How often the card asks again while the server has no explanation yet. */
export const EXPLANATION_POLL_MS = 3000;
/** Empty answers before the card stops asking; the next change or language still asks again. */
export const EXPLANATION_POLL_LIMIT = 5;

/**
 * The checked Nemotron explanation for a pending proposal (#1173). It asks once the card is
 * shown and polls while the answer is null, at most `EXPLANATION_POLL_LIMIT` times. It asks
 * again when the offer (`source`) or the language changes, and never for a decided proposal.
 * Null means "no text": the card shows nothing and never waits for this.
 */
export function useProposalExplanation(
  api: Api | null,
  proposalId: string | null | undefined,
  enabled: boolean,
  source: unknown,
): ProposalExplanation | null {
  const { language } = useLanguage();
  const [explanation, setExplanation] = useState<ProposalExplanation | null>(null);
  const identity = `${proposalId ?? ""}\u0000${JSON.stringify(source ?? null)}\u0000${language}`;
  // The identity the text was asked for: a changed offer or language drops the old text at once.
  const [asked, setAsked] = useState(identity);
  // The latest ask, so a late answer from a previous offer or language cannot show.
  const latest = useRef(identity);
  latest.current = identity;

  useEffect(() => {
    const current = `${proposalId ?? ""}\u0000${JSON.stringify(source ?? null)}\u0000${language}`;
    if (current !== asked) {
      setAsked(current);
      setExplanation(null);
    }
  }, [asked, language, proposalId, source]);

  useEffect(() => {
    if (!api || !enabled || !proposalId) return;
    let active = true;
    let timer: number | undefined;
    let answers = 0;
    const ask = async () => {
      answers += 1;
      let found: ProposalExplanation | null = null;
      try {
        found = await api.getProposalExplanation(proposalId, language);
      } catch {
        found = null;
      }
      if (!active) return;
      if (latest.current !== identity) return;
      if (found?.text) {
        setExplanation(found);
        return;
      }
      if (answers < EXPLANATION_POLL_LIMIT) timer = window.setTimeout(() => void ask(), EXPLANATION_POLL_MS);
    };
    void ask();
    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [api, enabled, identity, language, proposalId]);

  // A decided proposal shows no explanation, also one loaded while it was waiting.
  return enabled && asked === identity ? explanation : null;
}
