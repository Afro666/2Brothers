import { object, rows } from "@/api/gateway-map";
import { SUPPLIER_ID } from "@/api/supplier-id";
import type { Api } from "@/api/types";
import type { BuyingNote, BuyingNoteLine, ShortageRisk } from "@/types";

const RISKS: Record<string, ShortageRisk> = { SHORT: "SHORT", UNKNOWN: "UNKNOWN", AT_RISK: "AT_RISK", COVERED: "COVERED" };
const text = (value: unknown): string => {
  if (typeof value !== "string" || !value) throw new Error("a buying note line is missing its text");
  return value;
};

/**
 * The gateway's buying-note answer (`GET /suppliers/{id}/demand/buying-note`). `note: null`
 * (dropped) and `note: []` (nothing short) read as null. Failures reject so the page can say so.
 */
const day = (value: unknown): string => {
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) throw new Error("a buying note line has no date");
  return value;
};

export function mapBuyingNote(body: unknown): BuyingNote | null {
  const raw = object(body, "the buying note");
  const note = raw.note;
  if (note == null) return null;
  if (typeof raw.model !== "string" || !raw.model) throw new Error("the buying note has no model");
  const list = rows(raw, "note");
  if (list.length === 0) return null;
  const lines = list.map((row): BuyingNoteLine => {
    const risk = typeof row.risk === "string" ? RISKS[row.risk] : undefined;
    if (!risk) throw new Error("a buying note line has an unknown risk");
    return {
      productId: text(row.product_id),
      productName: text(row.product_name),
      date: day(row.date),
      risk,
      text: text(row.text),
    };
  });
  return { model: raw.model, lines };
}

export function createBuyingNoteHttp(
  call: (path: string, init?: RequestInit) => Promise<unknown>,
): Pick<Api, "getBuyingNote"> {
  return {
    async getBuyingNote(from, to, language) {
      const query = `from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&lang=${language}`;
      return mapBuyingNote(await call(`/v1/suppliers/${encodeURIComponent(SUPPLIER_ID)}/demand/buying-note?${query}`));
    },
  };
}
