import { describe, expect, it } from "vitest";

import { supplierName } from "./supplier-name";

describe("supplierName", () => {
  it("uses the kitchen's own supplier row first", () => {
    expect(supplierName("sup-valio", new Map([["sup-valio", "Valio Aimo Oy"]]))).toBe("Valio Aimo Oy");
  });

  it("names Valio when the kitchen has no row for it", () => {
    expect(supplierName("sup-valio", new Map())).toBe("Valio Aimo");
  });

  it("matches the Valio id case-insensitively", () => {
    expect(supplierName("SUP-VALIO", new Map())).toBe("Valio Aimo");
  });

  it("keeps an unknown id as it is", () => {
    expect(supplierName("sup-bakery-7", new Map())).toBe("sup-bakery-7");
  });
});
