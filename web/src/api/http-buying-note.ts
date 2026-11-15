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

/** 6 x 6 s covers the gateway's 35 s limit for one note. */
const BUSY_WAIT_MS = 6000;
const BUSY_RETRIES = 6;

export function createBuyingNoteHttp(
  call: (path: string, init?: RequestInit) => Promise<unknown>,
): Pick<Api, "getBuyingNote"> {
  return {
    async getBuyingNote(from, to, language) {
      const query = `from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}&lang=${language}`;
      const path = `/v1/suppliers/${encodeURIComponent(SUPPLIER_ID)}/demand/buying-note?${query}`;
      // BUYING_NOTE_BUSY: one note per supplier is written at a time (another reader, or the other
      // language). It takes at most 35 s and is cached after, so ask again instead of failing the page.
      for (let attempt = 0; ; attempt += 1) {
        try {
          return mapBuyingNote(await call(path));
        } catch (reason) {
          const busy = (reason as { details?: { code?: unknown } } | null)?.details?.code === "BUYING_NOTE_BUSY";
          if (!busy || attempt >= BUSY_RETRIES) throw reason;
          await new Promise((resolve) => setTimeout(resolve, BUSY_WAIT_MS));
        }
      }
    },
  };
}
