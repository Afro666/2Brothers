/** The contract's example answer (docs/contract.md, "Check a package's allergen label from a photo"). */
export const LABEL_ANSWER = {
  model: "nemotron-3.5-super-vl", duration_ms: 3100,
  order_id: "ORD-1042", product_id: "462775", in_order: true,
  outcome: "EXCLUDED_ALLERGEN",
  message: "The label declares peanuts, which this kitchen excludes. Do not use it; ask a person.",
  product_check: "CONFIRMED_BY_EAN",
  label: { product_name: "Arla", ean: "6408430000000",
    contains: [{ word: "MAITO", code: "AM" }],
    may_contain: [{ word: "maapähkinää", code: "AP" }],
    unknown_words: [] as string[] },
  excluded_hits: [{ code: "AP", level: "MAY_CONTAIN" }],
  differences: [{ code: "AP", kind: "LABEL_ADDS", text: "The label lists peanuts (may contain); the catalog does not." }],
  catalog_allergen_data: "KNOWN",
  please_check: [] as string[],
};
