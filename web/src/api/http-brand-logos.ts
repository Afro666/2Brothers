import { rows, text } from "@/api/gateway-map";
import type { Api, BrandLogo } from "@/api/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

const BACKGROUNDS = ["light", "dark", "own"] as const;

function optional(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

/**
 * `GET /v1/brands/logos` -> one row per brand. A logo is kept only for `found` with an
 * https URL; anything else is no logo, so the picture stays the kind tile.
 */
export function mapBrandLogos(body: unknown): BrandLogo[] {
  return rows(body, "logos").map((row) => {
    const status = row.status === "found" || row.status === "not_checked" ? row.status : "none";
    const url = optional(row.logo_url);
    const logoUrl = status === "found" && url?.startsWith("https://") ? url : null;
    const background = BACKGROUNDS.find((value) => value === row.background) ?? "light";
    return {
      brand: text(row.brand, "a brand name"),
      status,
      logoUrl,
      background: logoUrl ? background : null,
      domain: logoUrl ? optional(row.domain) : null,
      checkedAt: optional(row.checked_at),
    };
  });
}

/** Brand logos against the real gateway (gateway/brand_logos.py). It never calls Context.dev. */
export function createBrandLogosHttp(call: GatewayCall): Required<Pick<Api, "listBrandLogos">> {
  return {
    async listBrandLogos(brands) {
      const names = [...new Set(brands)];
      if (names.length === 0) return [];
      const query = new URLSearchParams(names.map((name) => ["name", name]));
      return mapBrandLogos(await call(`/v1/brands/logos?${query.toString()}`));
    },
  };
}
