/**
 * Plain words for the warning and reason codes the engine and gateway send
 * (engine/offers.py, engine/quantity.py, engine/gap.py, engine/padding.py, gateway/service.py).
 * A raw code never reaches the screen: an unknown one is turned into words.
 */
export interface CodeLabel {
  title: string;
  detail: string;
}

export const CODE_LABELS: Record<string, CodeLabel> = {
  OVER_BUDGET_WARNING: {
    title: "Above the weekly budget",
    detail: "A warning, not a block: you can still approve.",
  },
  CERTAINTY_PREMIUM_HIGH: {
    title: "Confirmed stock costs much more",
    detail: "The option with confirmed stock costs much more than the cheapest one. A warning, not a block.",
  },
  PARTIAL_STOCK: {
    title: "Only part is in stock",
    detail: "The supplier has only part of the amount for this delivery date.",
  },
  STOCK_UNKNOWN: {
    title: "Stock not confirmed",
    detail: "The supplier does not report stock for some lines. They confirm it later.",
  },
  PACK_SIZE_DERIVED: {
    title: "Rounded to whole packs",
    detail: "The amount is rounded up to whole packs of the product.",
  },
  LOT_SIZE_ROUNDED: {
    title: "Rounded to the order step",
    detail: "The supplier sells this in fixed steps, so the amount is rounded up.",
  },
  SUBSTITUTE_FAT_LEVEL: {
    title: "Different fat level",
    detail: "A substitute has another fat level than the one asked for. Check it suits the recipe.",
  },
  SUBSTITUTE_NEEDS_OK: {
    title: "Substitute needs your OK",
    detail: "A product replaces the one asked for. A person must accept the swap.",
  },
  EVENT_LINE: {
    title: "One-off event",
    detail: "This line is for a one-off event. It is kept out of the forecast.",
  },
  ALLERGEN_RULE: {
    title: "Excluded allergen",
    detail: "The product contains an allergen this kitchen excludes, so it cannot be ordered.",
  },
  ALLERGEN_DATA_MISSING: {
    title: "Allergen data missing",
    detail: "The catalog has no allergen data for one or more products. Check the label.",
  },
  CLOSING_PASSED: {
    title: "Order cut-off passed",
    detail: "The supplier's cut-off for this delivery date has passed.",
  },
  STOCK_COUNT_MISSING: {
    title: "Stock not counted",
    detail: "There is no recent stock count, so the amount assumes nothing is on the shelf.",
  },
  STANDING_ORDER_DRIFT: {
    title: "Use differs from the standing order",
    detail: "The kitchen uses more or less than its standing order. Check the amount.",
  },
  STOCKOUT_ADJUSTED: {
    title: "Adjusted for past stock-outs",
    detail: "Past sales were low because stock ran out, so the forecast is raised.",
  },
  MOV_PADDED: {
    title: "Filled up to the minimum order",
    detail: "Products the kitchen needs soon were added to reach the supplier's minimum order.",
  },
  COVER_CEILING: {
    title: "Capped at the stock limit",
    detail: "The amount is capped so the shelf does not hold too many days of stock.",
  },
  POSITION_OK: {
    title: "Stock is enough",
    detail: "Stock on hand and on order covers the need.",
  },
  BLOCKED_BY_RECALL: {
    title: "Blocked by a recall",
    detail: "A product on this order matches a food recall. It cannot be approved.",
  },
  proposal_explanation_failed: {
    title: "No model sentence for a proposal",
    detail: "Nemotron's short text was not written or did not pass the check. The card shows the decision record instead.",
  },
  kitchen_brief_read: {
    title: "Kitchen brief read",
    detail: "The Buyer read the kitchen's instructions and ordering rules.",
  },
  delivery_note_read: {
    title: "Delivery note read",
    detail: "The delivery note was read and compared with the order.",
  },
  EXPLANATION_UNAVAILABLE: {
    title: "Explanation unavailable",
    detail: "Nemotron's short text was not written or did not pass the check. The card shows the decision record instead.",
  },
};

/** #1591: a code a log step still sends raw ("kitchen_brief_read") as its plain title; other text as it is. */
export function plainCode(text: string, t: (text: string) => string): string {
  return Object.hasOwn(CODE_LABELS, text) ? t(CODE_LABELS[text].title) : text;
}

const CODE = /^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$/;

function words(code: string): string {
  const text = code.toLowerCase().replace(/_/g, " ");
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/** The plain title and sentence for a code; an unknown code is turned into words. */
export function codeLabel(code: string): CodeLabel {
  return (
    CODE_LABELS[code] ?? {
      title: words(code),
      detail: "The gateway flagged this. Check the order before you approve.",
    }
  );
}

/**
 * A gateway reason like "472710: ALLERGEN_RULE: the kitchen excludes AN" with the code in
 * plain words and, when known, the product name for its id. Other sentences stay as they are.
 */
export function plainReason(reason: string, names?: ReadonlyMap<string, string>): string {
  // "<id>: <CODE>: <rest>", or "<id>: <CODE>" alone ("461332: BLOCKED_BY_RECALL").
  const match = /^([^:]+): ([A-Z][A-Z0-9_]+)(?:: (.*))?$/s.exec(reason);
  if (!match || !CODE.test(match[2])) return reason;
  const [, product, code, rest] = match;
  const label = codeLabel(code);
  const name = names?.get(product) ?? product;
  return rest === undefined ? `${name}: ${label.title}. ${label.detail}` : `${name}: ${label.title}: ${rest}`;
}

/**
 * #1169: a reason with t(), where the code title plainReason put in it ("Peanut butter:
 * Excluded allergen: ...") is translated on its own when the whole sentence is not in the
 * dictionary. The product name and the gateway's own words after the title stay as they are.
 */
export function translateReason(text: string, t: (text: string) => string): string {
  const whole = t(text);
  if (whole !== text) return whole;
  // The title starts the text or follows a ": ".
  const starts = [0];
  for (let i = text.indexOf(": "); i >= 0; i = text.indexOf(": ", i + 2)) starts.push(i + 2);
  for (const start of starts) {
    for (const { title, detail } of Object.values(CODE_LABELS)) {
      if (!text.startsWith(title, start)) continue;
      const head = text.slice(0, start);
      const after = text.slice(start + title.length);
      if (after === `. ${detail}`) return `${head}${t(title)}. ${t(detail)}`;
      if (after === "" || after.startsWith(": ")) return `${head}${t(title)}${after}`;
    }
  }
  return text;
}
