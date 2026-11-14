/**
 * A menu-plan proposal with many lines: one week of lunches as one order. Used by tests of
 * the dense lines table, and by the mock inbox when `VITE_MOCK_MENU_PLAN` is "true" (a
 * screenshot or demo of a long order), so the default mock inbox and its counts stay as
 * they are. Prices and stock are invented demo figures, not Valio's.
 */
import type { ApprovalRequest, Offer, Order, OrderLine, Product } from "@/types";

const REQUESTED = "2026-11-16";
const OPEN = "2026-11-15T17:00:00+02:00";
const CLOSED = "2026-11-12T15:00:00+02:00";

interface Row {
  id: string;
  en: string;
  fi: string;
  brand: string;
  unit: string;
  quantity: number;
  price: number;
  /** Measured stock; 999999 is Valio's "unknown". */
  stock: number;
  closing?: string;
  why: string;
}

const ROWS: Row[] = [
  { id: "404151", en: "Valio Eila lactose free milk drink 1 L", fi: "Valio Eila laktoositon maitojuoma 1 l", brand: "Valio Eila", unit: "ST", quantity: 120, price: 1.62, stock: 2400,
    why: "120 L for 5 lunches: porridge Mon and Wed, sauce Tue, 260 covers a day at 92 ml each, less 18 L on the shelf." },
  { id: "404233", en: "Valio cooking cream 15 % 1 L", fi: "Valio ruokakerma 15 % 1 l", brand: "Valio", unit: "ST", quantity: 36, price: 3.48, stock: 999999,
    why: "36 L for the creamy salmon soup (Tue) and the mushroom sauce (Thu): 2 batches of 18 L." },
  { id: "404318", en: "Valio Oltermanni cheese 17 % 1 kg", fi: "Valio Oltermanni juusto 17 % 1 kg", brand: "Valio", unit: "KG", quantity: 14, price: 11.9, stock: 380,
    why: "14 kg: 260 covers × 2 days × 25 g on the salad bar, rounded up to whole kilos." },
  { id: "404402", en: "Valio butter unsalted 500 g", fi: "Valio voi suolaton 500 g", brand: "Valio", unit: "ST", quantity: 12, price: 4.35, stock: 900,
    why: "6 kg for baking and the roux: the recipe card asks 1.1 kg per day, plus a 10 % buffer." },
  { id: "404519", en: "Valio natural yoghurt 10 kg", fi: "Valio maustamaton jogurtti 10 kg", brand: "Valio", unit: "ST", quantity: 4, price: 28.6, stock: 64,
    why: "40 kg for breakfast bowls and the tzatziki: 150 g a cover on 2 days." },
  { id: "404620", en: "Valio PROfeel natural quark 1 kg", fi: "Valio PROfeel maitorahka 1 kg", brand: "Valio PROfeel", unit: "ST", quantity: 18, price: 4.95, stock: 999999,
    why: "18 kg for the Friday dessert: 260 covers × 70 g." },
  { id: "404711", en: "Finnish potatoes, peeled 5 kg", fi: "Kuoritut perunat 5 kg", brand: "Kotimaista", unit: "ST", quantity: 30, price: 8.4, stock: 600,
    why: "150 kg for 3 potato days at 190 g a cover, minus 12 kg already in the cold room." },
  { id: "404805", en: "Carrots, Finnish 10 kg", fi: "Porkkana 10 kg", brand: "Kotimaista", unit: "ST", quantity: 6, price: 9.2, stock: 140,
    why: "60 kg for soup, stew and grated salad." },
  { id: "404933", en: "Broiler fillet strips 2.5 kg", fi: "Broilerin fileesuikale 2,5 kg", brand: "Kariniemen", unit: "ST", quantity: 22, price: 21.5, stock: 75, closing: CLOSED,
    why: "55 kg for the Wednesday curry: 260 covers × 210 g raw weight." },
  { id: "405017", en: "Salmon fillet, skinless 1 kg", fi: "Lohifilee nahaton 1 kg", brand: "Norfresh", unit: "KG", quantity: 26, price: 17.8, stock: 999999,
    why: "26 kg for the Tuesday soup: 100 g a cover." },
  { id: "405104", en: "Oat flakes 3 kg", fi: "Kaurahiutale 3 kg", brand: "Myllärin", unit: "ST", quantity: 8, price: 6.1, stock: 320,
    why: "24 kg of porridge oats for 2 breakfasts at 45 g a cover." },
  { id: "405210", en: "Rye bread, sliced 1.2 kg", fi: "Ruisleipä viipaloitu 1,2 kg", brand: "Vaasan", unit: "ST", quantity: 40, price: 4.2, stock: 500,
    why: "48 kg of bread for the week: 2 slices a cover each day." },
  { id: "405322", en: "Lingonberries, frozen 2 kg", fi: "Puolukka pakaste 2 kg", brand: "Pakkasmarja", unit: "ST", quantity: 5, price: 12.3, stock: 0,
    why: "10 kg for the Friday quark dessert." },
  { id: "405418", en: "Valio Eila lactose free cream 38 % 1 L", fi: "Valio Eila laktoositon kuohukerma 38 % 1 l", brand: "Valio Eila", unit: "ST", quantity: 10, price: 5.6, stock: 220,
    why: "10 L whipped for the Friday dessert topping." },
];

function product(row: Row): Product {
  return {
    id: row.id,
    names: { en: row.en, fi: row.fi },
    brand: row.brand,
    vendorName: row.brand,
    category: "Menu plan",
    salesUnit: row.unit,
    baseUnit: row.unit === "KG" ? "KG" : "L",
    baseUnitsPerSalesUnit: null,
    units: [{ unitId: row.unit, sizeInBaseUnits: 1 }],
    fatPercent: null,
    temperature: null,
    allergens: [],
    labels: [],
    co2KgPerKg: null,
    deliveryReliability: null,
  };
}

function offer(row: Row, index: number): Offer {
  return {
    // Delivery facts (#1453) as a demo kitchen gets them: demo cut-off and lead time, some
    // reliability from Valio's data and some invented for the demo.
    cutoffSource: "demo",
    leadTimeDays: row.unit === "KG" ? 2 : 1,
    leadTimeSource: "demo",
    deliveryReliability: 0.9 + (index % 5) / 50,
    reliabilitySource: index % 3 === 0 ? "valio" : "demo",
    productId: row.id,
    requestedDate: REQUESTED,
    priceExVat: row.price,
    taxRatePercent: 14,
    comparisonPrice: null,
    comparisonUnit: null,
    availableAmount: row.stock,
    salesUnit: row.unit,
    availableDate: REQUESTED,
    closingTime: row.closing ?? OPEN,
    salesBlock: row.stock === 0,
  };
}

export const menuPlanLines: OrderLine[] = ROWS.map((row, index) => ({
  product: product(row),
  offer: offer(row, index),
  quantity: row.quantity,
  lineTotal: Math.round(row.quantity * row.price * 100) / 100,
  why: row.why,
}));

const totalExVat = Math.round(menuPlanLines.reduce((sum, line) => sum + (line.lineTotal ?? 0), 0) * 100) / 100;
const vat = Math.round(totalExVat * 0.14 * 100) / 100;

export const menuPlanOrder: Order = {
  id: "ORD-1050",
  status: "NEEDS_APPROVAL",
  urgency: "UNKNOWN",
  deliveryDate: REQUESTED,
  lines: menuPlanLines,
  supplierMustConfirm: [],
  totalExVat,
  vat,
  deliveryFee: null,
  totalInclVat: Math.round((totalExVat + vat) * 100) / 100,
  mov: { threshold: 250, current: totalExVat, deliveryFee: 25 },
};

export const menuPlanApproval: ApprovalRequest = {
  id: "APR-320",
  approvalRef: "APR-320",
  orderId: menuPlanOrder.id,
  requestedBy: "Head chef",
  createdAt: "2026-11-13T19:05:00+02:00",
  summary: "Menu plan, week 47: lunches Mon to Fri for 260 covers",
  lineCount: menuPlanLines.length,
  deliveryDate: REQUESTED,
  totalExVat,
  totalInclVat: menuPlanOrder.totalInclVat,
  reasons: [
    { rule: "The total is above your kitchen's budget warning.", detail: "A warning only. It does not block the order.", warning: true },
    { rule: "404933: order cut-off has passed", detail: "" },
    { rule: "405322: not available for this date", detail: "" },
    { rule: "463132: order cut-off has passed", detail: "" },
    { rule: "463335: order cut-off has passed", detail: "" },
    { rule: "Valio must confirm stock for: Valio cooking cream 15 % 1 L, Valio PROfeel natural quark 1 kg, Salmon fillet, skinless 1 kg.", detail: "" },
  ],
  suppliersToConfirm: [],
  status: "PENDING",
};
