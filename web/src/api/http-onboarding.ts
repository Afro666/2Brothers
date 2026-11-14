import { type Json, object } from "@/api/gateway-map";
import type { Api } from "@/api/types";
import { ApiError } from "@/api/types";
import type { FieldSource, KitchenAddress, KitchenBrandLookup, KitchenType, LookedUpField } from "@/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

const KITCHEN_TYPES: readonly KitchenType[] = ["hotel", "school", "hospital", "restaurant"];
const COLOR = /^#[0-9a-f]{6}$/i;

const string = (value: unknown): string | null => (typeof value === "string" && value.trim() ? value.trim() : null);

function source(value: unknown): FieldSource | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Json;
  return raw.provider === "Context.dev" && typeof raw.endpoint === "string"
    ? { provider: "Context.dev", endpoint: raw.endpoint }
    : null;
}

/**
 * One `{value, source}` pair. A value the page cannot use (a wrong type, a colour that is not
 * `#rrggbb`) becomes unknown: the field stays empty and the person fills it in. Nothing is guessed.
 */
function field<T>(raw: unknown, read: (value: unknown) => T | null): LookedUpField<T> {
  const pair = raw && typeof raw === "object" ? (raw as Json) : {};
  const value = pair.value == null ? null : read(pair.value);
  return { value, source: value === null ? null : source(pair.source) };
}

function address(value: unknown): KitchenAddress | null {
  if (!value || typeof value !== "object") return null;
  const raw = value as Json;
  const found: KitchenAddress = {
    street: string(raw.street),
    postalCode: string(raw.postal_code),
    city: string(raw.city),
    country: string(raw.country),
  };
  return Object.values(found).some((part) => part !== null) ? found : null;
}

function colors(value: unknown): string[] | null {
  if (!Array.isArray(value)) return null;
  const valid = value.filter((color): color is string => typeof color === "string" && COLOR.test(color));
  return valid.length ? valid : null;
}

/** An https address or an inline image: the only logo sources the page shows. */
function logo(value: unknown): string | null {
  const url = string(value);
  return url && (url.startsWith("https://") || url.startsWith("data:image/")) ? url : null;
}

/** `POST /v1/onboarding/lookup` (docs/contract.md, "Onboarding lookup (Context.dev)"). */
export function mapKitchenBrandLookup(body: unknown): KitchenBrandLookup {
  const raw = object(body, "the lookup answer");
  if (typeof raw.domain !== "string" || typeof raw.found !== "boolean") {
    throw new ApiError("INVALID_RESPONSE", "The lookup answer has no domain or no found flag.");
  }
  return {
    domain: raw.domain,
    found: raw.found,
    name: field(raw.name, string),
    logoUrl: field(raw.logo_url, logo),
    colors: field(raw.colors, colors),
    address: field(raw.address, address),
    kitchenType: field(raw.kitchen_type, (value) =>
      KITCHEN_TYPES.includes(value as KitchenType) ? (value as KitchenType) : null,
    ),
    openingHours: field(raw.opening_hours, string),
  };
}

/**
 * Onboarding against the real gateway (gateway/onboarding.py). The gateway calls Context.dev
 * with its own key; the browser never sees it. The route saves nothing.
 */
export function createOnboardingHttp(call: GatewayCall): Pick<Api, "lookupKitchenBrand"> {
  return {
    async lookupKitchenBrand(query) {
      return mapKitchenBrandLookup(
        await call("/v1/onboarding/lookup", { method: "POST", body: JSON.stringify(query) }),
      );
    },
  };
}
