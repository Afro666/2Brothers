import { describe, expect, it } from "vitest";

import { linkWordBody, mapKitchenWords } from "@/api/map-words";

const body = {
  aliases: [
    { phrase: "house milk", product_id: "463335", product_name: "Valio Eila 3 % milk", set_by: "aino", uses: 4 },
    { phrase: "the bread", product_id: "own-1", product_name: null, set_by: null, uses: 0 },
  ],
  unknown_items: [
    {
      phrase: "oat barista",
      times: 3,
      first_asked: "2026-11-10T07:12:00+00:00",
      last_asked: "2026-11-13T06:48:00+00:00",
    },
    { phrase: "blue cheese", times: 1, first_asked: null, last_asked: null },
  ],
};

describe("the kitchen's words", () => {
  it("maps the own names and the unknown words", () => {
    expect(mapKitchenWords(body)).toEqual({
      aliases: [
        { phrase: "house milk", productId: "463335", productName: "Valio Eila 3 % milk", setBy: "aino", uses: 4 },
        // A product the gateway names by its id only shows that id.
        { phrase: "the bread", productId: "own-1", productName: "own-1", setBy: null, uses: 0 },
      ],
      unknownItems: [
        {
          phrase: "oat barista",
          times: 3,
          firstAsked: "2026-11-10T07:12:00+00:00",
          lastAsked: "2026-11-13T06:48:00+00:00",
        },
        { phrase: "blue cheese", times: 1, firstAsked: null, lastAsked: null },
      ],
    });
  });

  it("maps a kitchen with no words to two empty lists", () => {
    expect(mapKitchenWords({ aliases: [], unknown_items: [] })).toEqual({ aliases: [], unknownItems: [] });
  });

  it.each([
    ["no alias list", { unknown_items: [] }],
    ["no unknown list", { aliases: [] }],
    ["an alias without a phrase", { ...body, aliases: [{ ...body.aliases[0], phrase: "" }] }],
    ["an alias without a product", { ...body, aliases: [{ ...body.aliases[0], product_id: null }] }],
    ["a use count that is text", { ...body, aliases: [{ ...body.aliases[0], uses: "4" }] }],
    ["a negative count", { ...body, unknown_items: [{ ...body.unknown_items[0], times: -1 }] }],
    ["a list", [body]],
  ])("refuses %s", (_, answer) => {
    expect(() => mapKitchenWords(answer)).toThrow(expect.objectContaining({ code: "INVALID_RESPONSE" }));
  });

  it("builds the PUT body", () => {
    expect(linkWordBody("  house milk ", "463335")).toEqual({ phrase: "house milk", product_id: "463335" });
  });
});
