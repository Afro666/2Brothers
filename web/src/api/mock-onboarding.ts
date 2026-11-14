import { ApiError } from "@/api/types";
import type { FieldSource, KitchenBrandLookup, LookedUpField } from "@/types";

/** The endpoints the gateway calls (docs/contract.md, "Onboarding lookup"). */
export const BRAND_RETRIEVE: FieldSource = { provider: "Context.dev", endpoint: "POST /v1/brand/retrieve" };
export const WEB_SCRAPE: FieldSource = { provider: "Context.dev", endpoint: "POST /v1/web/scrape" };

/** Context.dev refuses these with 422 FREE_EMAIL_DETECTED: the domain says nothing about the kitchen. */
const FREE_EMAIL_DOMAINS = new Set([
  "gmail.com",
  "googlemail.com",
  "outlook.com",
  "hotmail.com",
  "live.com",
  "yahoo.com",
  "icloud.com",
  "proton.me",
  "protonmail.com",
  "luukku.com",
  "suomi24.fi",
]);

const DOMAIN = /^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;

/** `chef@HotelKuusi.fi` or `https://www.hotelkuusi.fi/en/` -> `hotelkuusi.fi`; null when it is not a domain. */
export function domainOf(query: { email: string } | { website: string }): string | null {
  let host: string;
  if ("email" in query) {
    const match = /^[^\s@]+@([^\s@]+)$/.exec(query.email.trim());
    if (!match) return null;
    host = match[1];
  } else {
    host = query.website
      .trim()
      .replace(/^[a-z][a-z0-9+.-]*:\/\//i, "")
      .split(/[/?#]/)[0]
      .replace(/:\d+$/, "");
  }
  host = host.toLowerCase().replace(/^www\./, "").replace(/\.$/, "");
  return DOMAIN.test(host) ? host : null;
}

const found = <T>(value: T, source: FieldSource = BRAND_RETRIEVE): LookedUpField<T> => ({ value, source });
const unknown = <T>(): LookedUpField<T> => ({ value: null, source: null });

/** A spruce ("kuusi") on a dark green tile. Invented for the demo; not a real company's logo. */
const KUUSI_LOGO = `data:image/svg+xml;utf8,${encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><rect width="64" height="64" rx="14" fill="#1f4d3a"/>' +
    '<path d="M32 9 44 25h-6l9 12h-7l9 12H15l9-12h-7l9-12h-6z" fill="#e9d8a6"/><rect x="29" y="49" width="6" height="7" fill="#e9d8a6"/></svg>',
)}`;

/** Fictional kitchens the mock knows. Every name, domain and address is invented. */
const KNOWN: Record<string, Omit<KitchenBrandLookup, "domain" | "found">> = {
  "hotelkuusi.fi": {
    name: found("Hotel Kuusi"),
    logoUrl: found(KUUSI_LOGO),
    colors: found(["#1f4d3a", "#e9d8a6", "#c8553d"]),
    address: found({ street: "Satakunnankatu 41", postalCode: "33210", city: "Tampere", country: "Finland" }),
    kitchenType: found("hotel"),
    openingHours: found("Breakfast Mon-Fri 06:30-10:00, Sat-Sun 07:00-11:00; restaurant daily 17:00-22:00", WEB_SCRAPE),
  },
  // A thin profile: what the provider does not know stays unknown, never filled in.
  "lumikoulu.fi": {
    name: found("Lumi School"),
    logoUrl: unknown(),
    colors: unknown(),
    address: found({ street: null, postalCode: null, city: "Oulu", country: "Finland" }),
    kitchenType: found("school"),
    openingHours: unknown(),
  },
};

/** The mock of the gateway's onboarding lookup. */
export async function lookupKitchenBrandMock(
  query: { email: string } | { website: string },
): Promise<KitchenBrandLookup> {
  const domain = domainOf(query);
  if (!domain) {
    throw new ApiError(
      "INVALID_QUERY",
      "email" in query ? "That is not an email address." : "That is not a website address.",
    );
  }
  if ("email" in query && FREE_EMAIL_DOMAINS.has(domain)) {
    throw new ApiError(
      "FREE_EMAIL",
      "A personal email address says nothing about the kitchen. Type the kitchen's website instead.",
    );
  }
  const known = KNOWN[domain];
  if (known) return { domain, found: true, ...structuredClone(known) };
  return {
    domain,
    found: false,
    name: unknown(),
    logoUrl: unknown(),
    colors: unknown(),
    address: unknown(),
    kitchenType: unknown(),
    openingHours: unknown(),
  };
}
