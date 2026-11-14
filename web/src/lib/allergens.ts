/** The 14 EU allergens (Regulation 1169/2011, Annex II) with their GS1 allergen type codes. */
export const EU_ALLERGENS = [
  { code: "AW", name: "Gluten cereals" },
  { code: "AC", name: "Crustaceans" },
  { code: "AE", name: "Egg" },
  { code: "AF", name: "Fish" },
  { code: "AP", name: "Peanuts" },
  { code: "AY", name: "Soy" },
  { code: "AM", name: "Milk" },
  { code: "AN", name: "Tree nuts" },
  { code: "BC", name: "Celery" },
  { code: "BM", name: "Mustard" },
  { code: "AS", name: "Sesame" },
  { code: "AU", name: "Sulphites" },
  { code: "NL", name: "Lupin" },
  { code: "UM", name: "Molluscs" },
] as const;

/** GS1 code -> English name. */
export const ALLERGEN_NAMES: Record<string, string> = Object.fromEntries(
  EU_ALLERGENS.map(({ code, name }) => [code, name]),
);
