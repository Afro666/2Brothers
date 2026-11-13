import type {
  MenuPlanEntry,
  OwnProduct,
  Recipe,
  SharingConsent,
  StockItem,
  Supplier,
  SupplierDemandRow,
} from "@/types";

// Placeholder data for planning screens; only the milk catalog identifiers come from the milk case.
export const planningSuppliers: Supplier[] = [
  {
    id: "SUP-VALIO",
    name: "Valio Aimo",
    adapter: "valio_api",
    freeDeliveryThresholdEur: 250,
    deliveryFeeEur: 29,
    orderDays: [1, 2, 3, 4, 5],
    cutoffTime: "17:00",
    leadTimeDays: 1,
  },
  {
    id: "SUP-BAKERY",
    name: "Töölö Bakery",
    adapter: "manual",
    freeDeliveryThresholdEur: 80,
    deliveryFeeEur: 12,
    orderDays: [1, 3, 5],
    cutoffTime: "14:00",
    leadTimeDays: 2,
  },
  {
    id: "SUP-FISH",
    name: "Hakaniemi Fish",
    adapter: "csv",
    freeDeliveryThresholdEur: null,
    deliveryFeeEur: null,
    orderDays: null,
    cutoffTime: null,
    leadTimeDays: null,
  },
];

export const planningOwnProducts: OwnProduct[] = [
  {
    id: "OWN-RYE",
    name: "Rye bread loaf",
    unit: "PCS",
    packSize: 1,
    priceEur: 4.2,
    supplierId: "SUP-BAKERY",
    allergens: [{ code: "AW", name: "Gluten cereals", presence: "CONTAINS" }],
  },
  {
    id: "OWN-BUN",
    name: "Cinnamon bun",
    unit: "PCS",
    packSize: 1,
    priceEur: 2.1,
    supplierId: "SUP-BAKERY",
    allergens: null,
  },
  {
    id: "OWN-SALMON",
    name: "Salmon fillet",
    unit: "KG",
    packSize: 1,
    priceEur: null,
    supplierId: "SUP-FISH",
    allergens: [{ code: "AF", name: "Fish", presence: "CONTAINS" }],
  },
];

export const planningRecipes: Recipe[] = [
  {
    id: "REC-RICE-PUDDING",
    name: "Rice pudding",
    items: [{ productId: "463335", productName: "Valio Eila 3 % milk", unit: "L", qtyPerPortion: 0.15 }],
  },
  {
    id: "REC-SALMON-SOUP",
    name: "Salmon soup",
    items: [
      { productId: "OWN-SALMON", productName: "Salmon fillet", unit: "KG", qtyPerPortion: 0.12 },
      { productId: "462775", productName: "Arla lactose-free milk", unit: "L", qtyPerPortion: 0.1 },
      { productId: "OWN-RYE", productName: "Rye bread loaf", unit: "PCS", qtyPerPortion: 0.1 },
    ],
  },
  {
    id: "REC-COFFEE-SERVICE",
    name: "Coffee service",
    items: [
      { productId: "463335", productName: "Valio Eila 3 % milk", unit: "L", qtyPerPortion: 0.03 },
      { productId: "OWN-BUN", productName: "Cinnamon bun", unit: "PCS", qtyPerPortion: 1 },
    ],
  },
];

export const planningMenu: MenuPlanEntry[] = [
  {
    id: "MENU-1",
    date: "2026-11-16",
    meal: "Lunch",
    recipeId: "REC-SALMON-SOUP",
    covers: 160,
  },
  {
    id: "MENU-2",
    date: "2026-11-16",
    meal: "Dessert",
    recipeId: "REC-RICE-PUDDING",
    covers: 180,
  },
  {
    id: "MENU-3",
    date: "2026-11-16",
    meal: "Breakfast",
    recipeId: "REC-COFFEE-SERVICE",
    covers: 120,
  },
  {
    id: "MENU-4",
    date: "2026-11-17",
    meal: "Lunch",
    recipeId: "REC-SALMON-SOUP",
    covers: 140,
  },
  {
    id: "MENU-5",
    date: "2026-11-17",
    meal: "Dessert",
    recipeId: "REC-RICE-PUDDING",
    covers: 140,
  },
  {
    id: "MENU-6",
    date: "2026-11-18",
    meal: "Breakfast",
    recipeId: "REC-COFFEE-SERVICE",
    covers: 90,
  },
  {
    id: "MENU-7",
    date: "2026-11-18",
    meal: "Lunch",
    recipeId: "REC-SALMON-SOUP",
    covers: 180,
  },
  {
    id: "MENU-8",
    date: "2026-11-18",
    meal: "Dessert",
    recipeId: "REC-RICE-PUDDING",
    covers: 100,
  },
];

export const planningStock: StockItem[] = [
  {
    productId: "463335",
    productName: "Valio Eila 3 % milk",
    unit: "L",
    onHand: null,
    onOrder: 950,
    countedAt: null,
    lastDelivery: null,
  },
  {
    productId: "462775",
    productName: "Arla lactose-free milk",
    unit: "L",
    onHand: 18,
    onOrder: 0,
    countedAt: "2026-11-13T12:00:00+02:00",
    lastDelivery: "2026-11-12",
  },
  {
    productId: "462921",
    productName: "Valio Eila organic milk",
    unit: "L",
    onHand: null,
    onOrder: 0,
    countedAt: null,
    lastDelivery: null,
  },
  {
    productId: "463038",
    productName: "Valio Eila novobox milk",
    unit: "L",
    onHand: 0,
    onOrder: 0,
    countedAt: "2026-11-13T12:00:00+02:00",
    lastDelivery: null,
  },
  {
    productId: "464179",
    productName: "Arla novobox milk",
    unit: "L",
    onHand: null,
    onOrder: 0,
    countedAt: null,
    lastDelivery: null,
  },
  {
    productId: "OWN-SALMON",
    productName: "Salmon fillet",
    unit: "KG",
    onHand: 6,
    onOrder: 4,
    countedAt: "2026-11-13T12:00:00+02:00",
    lastDelivery: "2026-11-12",
  },
  {
    productId: "OWN-RYE",
    productName: "Rye bread loaf",
    unit: "PCS",
    onHand: 10,
    onOrder: 0,
    countedAt: "2026-11-13T12:00:00+02:00",
    lastDelivery: "2026-11-13",
  },
  {
    productId: "OWN-BUN",
    productName: "Cinnamon bun",
    unit: "PCS",
    onHand: null,
    onOrder: 0,
    countedAt: null,
    lastDelivery: null,
  },
];

export const planningSharing: SharingConsent[] = [
  { supplierId: "SUP-VALIO", shared: true },
  { supplierId: "SUP-BAKERY", shared: false },
  { supplierId: "SUP-FISH", shared: false },
];

const baseDemand: Array<Omit<SupplierDemandRow, "risk" | "suggestedBuy">> = [];
const kitchenNames = [
  ["K01", "K01 School 1 Tampere"],
  ["K04", "K04 Hotel Aurora Helsinki"],
  ["K07", "K07 Hospital kitchen Turku"],
  ["K12", "K12 Campus kitchen Espoo"],
  ["K18", "K18 Care home Oulu"],
] as const;
const demandSeed = [
  ["462775", "Arla lactose-free milk", "L", 51],
  ["462921", "Valio Eila organic milk", "L", null],
  ["463038", "Valio Eila novobox milk", "L", null],
  ["463335", "Valio Eila 3 % milk", "L", null],
  ["464179", "Arla novobox milk", "L", null],
] as const;

for (const date of ["2026-11-16", "2026-11-17", "2026-11-18"]) {
  for (const [index, [productId, productName, unit, available]] of demandSeed.entries()) {
    const forecastDemand = 220 + index * 35;
    const kitchenCount = 3 + (index % 2);
    const basePerKitchen = Math.floor((forecastDemand / kitchenCount) * 100) / 100;
    const byKitchen = Array.from({ length: kitchenCount }, (_, kitchenIndex) => ({
      kitchenId: kitchenNames[kitchenIndex][0],
      kitchenName: kitchenNames[kitchenIndex][1],
      demand:
        kitchenIndex === kitchenCount - 1
          ? Math.round((forecastDemand - basePerKitchen * (kitchenCount - 1)) * 100) / 100
          : basePerKitchen,
    }));
    baseDemand.push({
      productId,
      productName,
      unit,
      date,
      forecastDemand: byKitchen.reduce((sum, kitchen) => sum + kitchen.demand, 0),
      kitchens: byKitchen.length,
      byKitchen,
      available,
    });
  }
}

export const planningSupplierDemand = baseDemand;
