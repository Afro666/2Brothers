import { type Json, object, rows, text } from "@/api/gateway-map";
import { ApiError, type KitchenWords } from "@/api/types";

/**
 * `GET /aliases` (gateway/memory.py) to the UI type: the kitchen's own names for products and
 * the words of requests that matched no product. A product the gateway names by its id only
 * shows that id as its name.
 */

function count(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
  }
  return value;
}

const optionalText = (value: unknown): string | null => (typeof value === "string" && value ? value : null);

export function mapKitchenWords(body: unknown): KitchenWords {
  object(body, "the kitchen's words");
  return {
    aliases: rows(body, "aliases").map((row) => {
      const productId = text(row.product_id, "an alias product_id");
      return {
        phrase: text(row.phrase, "an alias phrase"),
        productId,
        productName: optionalText(row.product_name) ?? productId,
        setBy: optionalText(row.set_by),
        uses: count(row.uses, "an alias use count"),
      };
    }),
    unknownItems: rows(body, "unknown_items").map((row) => ({
      phrase: text(row.phrase, "an unknown phrase"),
      times: count(row.times, "an unknown phrase's count"),
      firstAsked: optionalText(row.first_asked),
      lastAsked: optionalText(row.last_asked),
    })),
  };
}

/** The body of `PUT /aliases`. */
export function linkWordBody(phrase: string, productId: string): Json {
  return { phrase: phrase.trim(), product_id: productId };
}
