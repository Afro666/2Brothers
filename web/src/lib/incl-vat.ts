import { formatEur } from "@/lib/format";
import type { TranslationVariables } from "@/lib/i18n";

type Translate = (text: string, vars?: TranslationVariables) => string;

/** What carries a total incl VAT: `inclVatUnknown` is set when the gateway's `total_incl_vat` is null. */
export interface InclVatTotal {
  totalInclVat: number;
  inclVatUnknown?: string[];
}

/**
 * "€91.20 incl VAT", or "incl VAT: unknown (Lettuce)" when a line's VAT rate is unknown
 * (docs/contract.md "VAT per product"): never the approved figure called a total incl VAT.
 */
export function inclVatText(item: InclVatTotal, t: Translate): string {
  if (!item.inclVatUnknown) return t("{amount} incl VAT", { amount: formatEur(item.totalInclVat) });
  return item.inclVatUnknown.length
    ? t("incl VAT: unknown ({names})", { names: item.inclVatUnknown.join(", ") })
    : t("incl VAT: unknown");
}
