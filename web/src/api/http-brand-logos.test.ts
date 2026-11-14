import { describe, expect, it, vi } from "vitest";

import { createBrandLogosHttp, mapBrandLogos } from "@/api/http-brand-logos";

const FOUND = {
  brand: "Valio",
  status: "found",
  logo_url: "https://media.brand.dev/valio.png",
  background: "own",
  domain: "valio.fi",
  checked_at: "2026-11-14T12:00:00+00:00",
  source: { provider: "Context.dev", endpoint: "POST /v1/brand/retrieve" },
};

describe("brand logos (contract: Product pictures)", () => {
  it("maps found, none and not_checked rows", () => {
    expect(
      mapBrandLogos({
        logos: [
          FOUND,
          { brand: "HK", status: "none", logo_url: null, background: null, domain: null, checked_at: "2026-11-14T12:00:00+00:00", source: null },
          { brand: "Arla", status: "not_checked", logo_url: null, background: null, domain: null, checked_at: null, source: null },
        ],
      }),
    ).toEqual([
      { brand: "Valio", status: "found", logoUrl: "https://media.brand.dev/valio.png", background: "own", domain: "valio.fi", checkedAt: "2026-11-14T12:00:00+00:00" },
      { brand: "HK", status: "none", logoUrl: null, background: null, domain: null, checkedAt: "2026-11-14T12:00:00+00:00" },
      { brand: "Arla", status: "not_checked", logoUrl: null, background: null, domain: null, checkedAt: null },
    ]);
  });

  it("never shows a logo that is not https or has an unknown status or background", () => {
    const [plain, odd, blue] = mapBrandLogos({
      logos: [
        { ...FOUND, logo_url: "http://plain.example/logo.png" },
        { ...FOUND, status: "maybe" },
        { ...FOUND, background: "blue" },
      ],
    });
    expect(plain.logoUrl).toBeNull();
    expect(odd).toMatchObject({ status: "none", logoUrl: null });
    expect(blue).toMatchObject({ background: "light" });
  });

  it("asks once with every name repeated as a parameter", async () => {
    const call = vi.fn().mockResolvedValue({ logos: [FOUND] });
    const api = createBrandLogosHttp(call);
    await api.listBrandLogos(["Valio", "Reuter & Stolt", "Valio"]);
    expect(call).toHaveBeenCalledWith("/v1/brands/logos?name=Valio&name=Reuter+%26+Stolt");
  });

  it("asks nothing for no names", async () => {
    const call = vi.fn();
    expect(await createBrandLogosHttp(call).listBrandLogos([])).toEqual([]);
    expect(call).not.toHaveBeenCalled();
  });
});
