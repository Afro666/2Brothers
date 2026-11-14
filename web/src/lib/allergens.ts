/** The 14 EU allergens (Regulation 1169/2011 Annex II) with their GS1 allergen type codes. */
export const EU_ALLERGENS = [
  { code: "AM", name: "Milk" },
  { code: "AW", name: "Gluten cereals" },
  { code: "AE", name: "Egg" },
  { code: "AF", name: "Fish" },
  { code: "AN", name: "Tree nuts" },
  { code: "AP", name: "Peanuts" },
  { code: "AS", name: "Sesame" },
  { code: "AY", name: "Soy" },
  { code: "AC", name: "Crustaceans" },
  { code: "UM", name: "Molluscs" },
  { code: "BC", name: "Celery" },
  { code: "BM", name: "Mustard" },
  { code: "AU", name: "Sulphites" },
  { code: "NL", name: "Lupin" },
] as const;

/**
 * The GS1 member codes beyond the 14 EU groups, as `agent/label.py NAMES` has them.
 * A code that is not here keeps its code: a guessed name would be a wrong warning.
 */
export const MEMBER_ALLERGENS: Record<string, string> = {
  ML: "Lactose",
  UW: "Wheat",
  NR: "Rye",
  GB: "Barley",
  GS: "Spelt",
  GK: "Kamut",
  GO: "Oats",
  SA: "Almonds",
  SC: "Cashew nuts",
  SH: "Hazelnuts",
  SM: "Macadamia nuts",
  SP: "Pecan nuts",
  SR: "Brazil nuts",
  ST: "Pistachio nuts",
  SW: "Walnuts",
};

const ALLERGEN_NAMES: Record<string, string> = {
  ...Object.fromEntries(EU_ALLERGENS.map(({ code, name }) => [code, name])),
  ...MEMBER_ALLERGENS,
};

/** Every allergen chip's name, from the code. A code in no table reads "Other allergen (<code>)", never the sender's word. */
export function allergenName(
  code: string,
  t: (text: string, vars?: Record<string, string | number>) => string,
): string {
  const name = Object.hasOwn(ALLERGEN_NAMES, code) ? ALLERGEN_NAMES[code] : null;
  return name ? t(name) : t("Other allergen ({code})", { code });
}
