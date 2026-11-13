import { afterEach, describe, expect, it, vi } from "vitest";

import { gatewayRequest } from "@/api/http";
import { mapMoney } from "@/api/map";

describe("mapMoney", () => {
  it("reads a contract decimal string", () => {
    expect(mapMoney("149.02")).toBe(149.02);
    expect(mapMoney("0")).toBe(0);
  });

  it.each([149.02, "", "1e5", "12,50", "abc", null, "9".repeat(400)])("rejects %j", (value) => {
    expect(() => mapMoney(value, "expected_total")).toThrow(/expected_total/);
  });
});

describe("gatewayRequest", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("turns the contract's error body into an ApiError with its code", async () => {
    const body = JSON.stringify({ error: { code: "TOTAL_MISMATCH", message: "The total moved." } });
    vi.stubGlobal("fetch", async () => new Response(body, { status: 409 }));
    await expect(gatewayRequest("http://gateway/", "/tools/place_order")).rejects.toMatchObject({
      code: "TOTAL_MISMATCH",
      message: "The total moved.",
    });
  });

  it("reports an unreachable gateway", async () => {
    vi.stubGlobal("fetch", async () => {
      throw new TypeError("fetch failed");
    });
    await expect(gatewayRequest("http://gateway", "/x")).rejects.toMatchObject({ code: "NETWORK" });
  });

  it("returns the JSON body on success", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ products: [] }), { status: 200 }));
    await expect(gatewayRequest("http://gateway", "/tools/search_products")).resolves.toEqual({ products: [] });
  });
});
