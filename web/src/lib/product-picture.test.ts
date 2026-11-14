import { describe, expect, it } from "vitest";

import { FALLBACK_PICTURE, pictureFor } from "./product-picture";

describe("pictureFor", () => {
  it.each([
    ["Valio Eila® 3 % milk drink 1 l lactose free", "", "milk and cream"],
    ["Valio Edam 17 % e1 kg slices", "", "cheese"],
    ["Kieku Barn egg L6 408g", "", "eggs"],
    ["POTATO WASHED 1KG", "", "potato"],
    ["Kalavapriikki salmon fillet A, ASC, apx. 10 kg", "", "fish and seafood"],
    ["Kariniemen Chicken breastfillet natural", "", "chicken and poultry"],
    ["Barilla 5kg Fusilli dry pasta", "", "pasta and noodles"],
    ["Kulta Katriina Traditional fine ground filter coffee RAC 5x1kg", "", "coffee and tea"],
  ])("%s is %s", (en, fi, kind) => {
    expect(pictureFor(en, fi).kind).toBe(kind);
  });

  it("puts a narrower kind before a wider one", () => {
    expect(pictureFor("Ingman Strawberry Ice Cream 5000ml").kind).toBe("ice cream");
    expect(pictureFor("Nic Hazelnut crunch 1kg").kind).toBe("nuts");
    expect(pictureFor("Paulig espresso coffee beans 1kg").kind).toBe("coffee and tea");
  });

  it("reads a Finnish compound by its last word, not a word inside it", () => {
    expect(pictureFor("", "Valio kuohukerma 2 dl").kind).toBe("milk and cream");
    expect(pictureFor("", "Birkkalan speltti 20 kg").kind).not.toBe("fish and seafood");
  });

  it("does not picture a napkin or a plate as the food in its name", () => {
    expect(pictureFor("DUNI Bio Dunisoft napkin kiwi 40x40cm").kind).toBe("napkins and table linen");
    expect(pictureFor("TRAMONTINA 40X30X1,8CM PIZZA PLATE").kind).toBe("tableware and kitchen tools");
    expect(pictureFor("TRE SENSI 6KPCS/15CL WINE GLASS").kind).toBe("tableware and kitchen tools");
  });

  it("gives a plain parcel when no rule matches", () => {
    expect(pictureFor("RAPID SUPREME S50 XYZ")).toBe(FALLBACK_PICTURE);
    expect(pictureFor(null, undefined)).toBe(FALLBACK_PICTURE);
  });
});
