import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapKitchenBrandLookup } from "@/api/http-onboarding";

const SOURCE = { provider: "Context.dev", endpoint: "POST /v1/brand/retrieve" };
/** The gateway's answer for a hotel chain, from its test on a recorded Context.dev reply (#602). */
const FOUND = {
  domain: "scandichotels.com",
  found: true,
  name: { value: "Scandic Hotels", source: SOURCE },
  logo_url: { value: "https://media.brand.dev/88e73623.svg", source: SOURCE },
  colors: { value: ["#d02f32", "#e48c94", "#040404"], source: SOURCE },
  address: {
    value: { street: "Sveavägen 167", postal_code: "102 33", city: "Stockholm", country: "Sweden" },
    source: SOURCE,
  },
  kitchen_type: { value: "hotel", source: SOURCE },
  opening_hours: { value: null, source: null },
};

function gateway(answer: () => unknown) {
  const calls: { route: string; body: unknown }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({ route: `${init.method ?? "GET"} ${url}`, body: init.body ? JSON.parse(init.body as string) : null });
    const body = answer();
    return body instanceof Response ? body : new Response(JSON.stringify(body));
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("Onboarding lookup on the real gateway", () => {
  it("posts the email or website and maps the answer field by field", async () => {
    const calls = gateway(() => FOUND);
    const api = createHttpApi("/api");
    expect(api.live!.has("lookupKitchenBrand")).toBe(true);
    const lookup = await api.lookupKitchenBrand({ website: "https://www.scandichotels.com" });
    expect(calls).toEqual([
      { route: "POST /api/v1/onboarding/lookup", body: { website: "https://www.scandichotels.com" } },
    ]);
    expect(lookup).toMatchObject({ domain: "scandichotels.com", found: true });
    expect(lookup.name).toEqual({ value: "Scandic Hotels", source: SOURCE });
    expect(lookup.address.value).toEqual({
      street: "Sveavägen 167",
      postalCode: "102 33",
      city: "Stockholm",
      country: "Sweden",
    });
    expect(lookup.kitchenType.value).toBe("hotel");
    expect(lookup.openingHours).toEqual({ value: null, source: null });
  });

  it("keeps an unknown domain unknown: every field empty, nothing guessed", () => {
    const empty = { value: null, source: null };
    const lookup = mapKitchenBrandLookup({
      domain: "nobody.example",
      found: false,
      name: empty,
      logo_url: empty,
      colors: empty,
      address: empty,
      kitchen_type: empty,
      opening_hours: empty,
    });
    expect(lookup.found).toBe(false);
    for (const key of ["name", "logoUrl", "colors", "address", "kitchenType", "openingHours"] as const) {
      expect(lookup[key]).toEqual(empty);
    }
  });

  it("drops values the page cannot trust instead of showing them", () => {
    const lookup = mapKitchenBrandLookup({
      ...FOUND,
      logo_url: { value: "javascript:alert(1)", source: SOURCE },
      colors: { value: ["red", "#12345", "#0a0b0c"], source: SOURCE },
      kitchen_type: { value: "casino", source: SOURCE },
      address: { value: { street: "", city: null }, source: SOURCE },
    });
    expect(lookup.logoUrl).toEqual({ value: null, source: null });
    expect(lookup.colors.value).toEqual(["#0a0b0c"]);
    expect(lookup.kitchenType).toEqual({ value: null, source: null });
    expect(lookup.address).toEqual({ value: null, source: null });
  });

  it("passes the gateway's refusals on with their codes", async () => {
    // api/http.ts reports every 429 as RATE_LIMITED, whatever code the gateway names.
    for (const [status, sent, code] of [
      [422, "FREE_EMAIL", "FREE_EMAIL"],
      [429, "LOOKUP_RATE_LIMITED", "RATE_LIMITED"],
      [502, "LOOKUP_UNAVAILABLE", "LOOKUP_UNAVAILABLE"],
    ] as const) {
      gateway(() => new Response(JSON.stringify({ error: { code: sent, message: sent } }), { status }));
      await expect(createHttpApi("/api").lookupKitchenBrand({ email: "chef@gmail.com" })).rejects.toMatchObject({
        code,
      });
    }
  });

  it("refuses an answer without a domain or a found flag", () => {
    expect(() => mapKitchenBrandLookup({ name: {} })).toThrow(/domain/);
  });
});
