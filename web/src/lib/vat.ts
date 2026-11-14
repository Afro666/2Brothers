/** What a screen calls "incl VAT" (docs/contract.md "VAT per product", #1630). */
export interface VatTotals {
  /** The approve figure (`expected_total`). Not a total incl VAT when a rate is unknown. */
  totalInclVat: number;
  inclVat?: number | null;
  vatUnknown?: string[];
}

/** The total incl VAT, or null when a line's VAT rate is unknown. An older answer without it keeps the approve figure. */
export function inclVatOf(totals: VatTotals): number | null {
  if (totals.vatUnknown?.length || totals.inclVat === null) return null;
  return totals.inclVat ?? totals.totalInclVat;
}

type Translate = (text: string, vars?: Record<string, string | number>) => string;

/** "€91.20 incl VAT", or "incl VAT: unknown (Oat drink)" when a rate is unknown: never the approve figure as incl VAT. */
export function inclVatText(totals: VatTotals, t: Translate, formatEur: (value: number | null) => string): string {
  const inclVat = inclVatOf(totals);
  if (inclVat !== null) return t("{amount} incl VAT", { amount: formatEur(inclVat) });
  const names = (totals.vatUnknown ?? []).join(", ");
  return names ? t("incl VAT: unknown ({names})", { names }) : t("incl VAT: unknown");
}
