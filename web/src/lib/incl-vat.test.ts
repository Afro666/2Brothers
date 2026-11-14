import { describe, expect, it } from "vitest";

import { formatEur } from "@/lib/format";
import { inclVatText } from "@/lib/incl-vat";

const t = (text: string, vars: Record<string, string | number> = {}) =>
  text.replace(/\{(\w+)\}/g, (_, key: string) => String(vars[key] ?? `{${key}}`));

describe("inclVatText", () => {
  it("shows the total incl VAT when every rate is known", () => {
    expect(inclVatText({ totalInclVat: 91.2 }, t)).toBe(`${formatEur(91.2)} incl VAT`);
  });

  it("says incl VAT is unknown with the product names, never the ex-VAT sum", () => {
    const text = inclVatText({ totalInclVat: 80, inclVatUnknown: ["Lettuce", "Dill"] }, t);
    expect(text).toBe("incl VAT: unknown (Lettuce, Dill)");
    expect(text).not.toContain(formatEur(80));
    expect(inclVatText({ totalInclVat: 80, inclVatUnknown: [] }, t)).toBe("incl VAT: unknown");
  });
});
