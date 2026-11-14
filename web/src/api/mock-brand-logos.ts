import type { BrandLogo } from "@/api/types";

/**
 * Sample data: Valio's icon as Context.dev returned it on 2026-11-14; most brands have no
 * logo, so most products keep their kind tile, as on the live site.
 */
const VALIO: Omit<BrandLogo, "brand"> = {
  status: "found",
  logoUrl: "https://media.brand.dev/1696e33d-d888-40c5-9517-143deb2fb788.png",
  background: "own",
  domain: "valio.fi",
  checkedAt: "2026-11-14T12:00:00+00:00",
};
const KNOWN: Record<string, Omit<BrandLogo, "brand">> = {
  Valio: VALIO,
  "Valio Eila": VALIO,
  Arla: { status: "none", logoUrl: null, background: null, domain: null, checkedAt: "2026-11-14T12:00:00+00:00" },
};
const NOT_CHECKED: Omit<BrandLogo, "brand"> = {
  status: "not_checked",
  logoUrl: null,
  background: null,
  domain: null,
  checkedAt: null,
};

export async function listBrandLogosMock(brands: string[]): Promise<BrandLogo[]> {
  return [...new Set(brands)].map((brand) => ({ brand, ...(KNOWN[brand] ?? NOT_CHECKED) }));
}
