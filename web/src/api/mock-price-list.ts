import type { PriceListRead, PriceListRow } from "@/api/types";
import { ApiError } from "@/api/types";

/** The mock's pause before it answers, so the "reading" state shows as it does live. */
export const PRICE_LIST_MOCK_DELAY_MS = 600;

/** The mock suppliers whose prices come from an API (mocks/planning.ts). */
const API_SUPPLIERS = new Set(["SUP-VALIO"]);

function row(
  printed: PriceListRow["printed"],
  draft: PriceListRow["draft"],
  reasons: PriceListRow["reasons"] = [],
  match: PriceListRow["match"] = null,
): PriceListRow {
  return { printed, status: reasons.length > 0 ? "PLEASE_CHECK" : "READ", reasons, draft, match };
}

/**
 * A sample of what the gateway answers for the prepared bakery price list (docs/contract.md,
 * "Read a supplier's price list from a photo"). For the mock bakery two rows match its own
 * products: one at a new price, one at the same price. Two rows need a person.
 */
export function priceListSample(supplierId: string): PriceListRead {
  const bakery = supplierId === "SUP-BAKERY";
  return {
    model: "nemotron-3.5-super-vl",
    durationMs: 5200,
    supplierId,
    currency: "EUR",
    vat: "INCLUDED",
    truncated: false,
    rows: [
      row(
        { name: "Rye bread loaf", price: "4,40 €", priceUnit: "kpl", pack: "800 g" },
        { name: "Rye bread loaf", unit: "ST", baseUnit: "KG", packSize: 0.8, priceEur: 4.4 },
        [],
        bakery ? { productId: "OWN-RYE", name: "Rye bread loaf", priceEur: 4.2, kind: "PRICE_CHANGED" } : null,
      ),
      row(
        { name: "Cinnamon bun", price: "2,10 €", priceUnit: "kpl", pack: null },
        { name: "Cinnamon bun", unit: "ST", baseUnit: null, packSize: null, priceEur: 2.1 },
        [],
        bakery ? { productId: "OWN-BUN", name: "Cinnamon bun", priceEur: 2.1, kind: "SAME" } : null,
      ),
      row(
        { name: "Oat sourdough loaf", price: "5,20 €", priceUnit: "kpl", pack: "750 g" },
        { name: "Oat sourdough loaf", unit: "ST", baseUnit: "KG", packSize: 0.75, priceEur: 5.2 },
      ),
      row(
        { name: "Karelian pies", price: "9,80 €", priceUnit: "kg", pack: null },
        { name: "Karelian pies", unit: "KG", baseUnit: null, packSize: null, priceEur: 9.8 },
      ),
      row(
        { name: "Seed rolls", price: "0,95", priceUnit: null, pack: null },
        { name: "Seed rolls", unit: null, baseUnit: null, packSize: null, priceEur: null },
        ["PRICE_UNIT_MISSING"],
      ),
      row(
        { name: "Butter croissant", price: "1,60 €", priceUnit: "kpl", pack: "6 x" },
        { name: "Butter croissant", unit: "ST", baseUnit: null, packSize: null, priceEur: 1.6 },
        ["PACK_UNCLEAR"],
      ),
    ],
  };
}

/**
 * The mock reads no photo: every photo gets the sample after a short pause. Like the gateway,
 * a supplier with an API is refused (422 `SUPPLIER_HAS_API`). It saves nothing.
 */
export async function readPriceListPhotoMock(supplierId: string): Promise<PriceListRead> {
  await new Promise((resolve) => setTimeout(resolve, PRICE_LIST_MOCK_DELAY_MS));
  if (API_SUPPLIERS.has(supplierId)) {
    throw new ApiError("SUPPLIER_HAS_API", "This supplier's prices come from its API.", {}, 422);
  }
  return priceListSample(supplierId);
}
