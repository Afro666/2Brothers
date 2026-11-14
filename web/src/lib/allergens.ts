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
