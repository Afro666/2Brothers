/**
 * The milk case from docs/valio-data.md: "1,000 L of lactose-free milk by
 * Monday", asked Fri 13 Nov 2026 21:00 for delivery Mon 16 Nov.
 *
 * From the live API (docs/valio-data.md): the five product codes, the
 * €/L of 462775 (2.57) and 462921 (2.19), the 51 ST stock, the unknown-stock
 * sentinels, and the closing times (11-12 15:00 already passed; 11-15 17:00).
 *
 * PLACEHOLDERS (not in the doc; replace with a live /api/price answer):
 * the prices of 463038, 463335 and 464179, the MOV threshold and delivery
 * fee, fat % where marked, temperature codes, reliability, CO2, Finnish
 * names, the mandate, and the audit times.
 */
import type {
  ApprovalRequest,
  AuditEvent,
  ChefRequest,
  Mandate,
  Offer,
  Order,
  OrderLine,
  Product,
  SubstituteOption,
} from "@/types";

/** The "now" every mock is seen from. Components take it as a prop, so tests are stable. */
export const MOCK_NOW = new Date("2026-11-13T21:00:00+02:00");

const REQUESTED = "2026-11-16";
const DAIRY_VAT = 13.5;
const MILK = { code: "AM", name: "Milk", presence: "CONTAINS" } as const;
const CHILLED = { code: 2, label: "Chilled, +2 to +6 °C" };

export const products = {
  arlaUht1l: {
    id: "462775",
    names: { en: "Arla 1 L lactose free fat free UHT milk drink", fi: "Arla laktoositon rasvaton UHT-maitojuoma 1 l" },
    brand: "Arla",
    vendorName: "Arla Oy",
    category: "Milk drinks",
    salesUnit: "ST",
    baseUnit: "L",
    baseUnitsPerSalesUnit: 1,
    units: [
      { unitId: "KI", sizeInBaseUnits: 12 },
      { unitId: "ST", sizeInBaseUnits: 1 },
    ],
    fatPercent: 0,
    temperature: { code: 1, label: "Ambient (UHT)" },
    allergens: [MILK],
    labels: ["FINNISH_HEART_SYMBOL"],
    co2KgPerKg: 1.3,
    deliveryReliability: 0.97,
  },
  eilaOrganic1l: {
    id: "462921",
    names: { en: "Valio Eila organic lactose free milk drink 1 L", fi: "Valio Eila luomu laktoositon maitojuoma 1 l" },
    brand: "Valio Eila",
    vendorName: "Valio Oy",
    category: "Milk drinks",
    salesUnit: "KI",
    baseUnit: "L",
    baseUnitsPerSalesUnit: 5,
    units: [
      { unitId: "KI", sizeInBaseUnits: 5 },
      { unitId: "ST", sizeInBaseUnits: 1 },
    ],
    fatPercent: null,
    temperature: CHILLED,
    allergens: [MILK],
    labels: ["EU_ORGANIC_FARMING", "GOODS_FROM_FINLAND_BLUE_SWAN"],
    co2KgPerKg: 1.3,
    deliveryReliability: 0.94,
  },
  eilaNovobox10l: {
    id: "463038",
    names: { en: "Valio Eila lactose free milk drink 10 L novobox" },
    brand: "Valio Eila",
    vendorName: "Valio Oy",
    category: "Milk drinks",
    salesUnit: "KI",
    baseUnit: "L",
    baseUnitsPerSalesUnit: 20,
    units: [
      { unitId: "KI", sizeInBaseUnits: 20 },
      { unitId: "ST", sizeInBaseUnits: 10 },
    ],
    fatPercent: null,
    temperature: CHILLED,
    allergens: [MILK],
    labels: ["GOODS_FROM_FINLAND_BLUE_SWAN"],
    co2KgPerKg: 1.3,
    deliveryReliability: 0.91,
  },
  eila3pct1l: {
    id: "463335",
    names: { en: "Valio Eila 3 % lactose free milk drink 1 L", fi: "Valio Eila 3 % laktoositon maitojuoma 1 l" },
    brand: "Valio Eila",
    vendorName: "Valio Oy",
    category: "Milk drinks",
    salesUnit: "ST",
    baseUnit: "L",
    baseUnitsPerSalesUnit: 1,
    units: [
      { unitId: "KI", sizeInBaseUnits: 5 },
      { unitId: "ST", sizeInBaseUnits: 1 },
    ],
    fatPercent: 3,
    temperature: CHILLED,
    allergens: [MILK],
    labels: ["GOODS_FROM_FINLAND_BLUE_SWAN"],
    co2KgPerKg: 1.3,
    deliveryReliability: null,
  },
  arlaEsl10l: {
    id: "464179",
    names: { en: "Arla lactose free milk drink 10 L novobox ESL" },
    brand: "Arla",
    vendorName: "Arla Oy",
    category: "Milk drinks",
    salesUnit: "ST",
    baseUnit: "L",
    baseUnitsPerSalesUnit: 10,
    units: [{ unitId: "ST", sizeInBaseUnits: 10 }],
    fatPercent: null,
    temperature: null,
    // Allergen data missing in the catalog: shown as unknown, never as allergen-free.
    allergens: null,
    labels: [],
    co2KgPerKg: null,
    deliveryReliability: 0.88,
  },
} satisfies Record<string, Product>;

function offer(p: Product, o: Omit<Offer, "productId" | "requestedDate" | "taxRatePercent" | "salesUnit" | "salesBlock">): Offer {
  return { productId: p.id, requestedDate: REQUESTED, taxRatePercent: DAIRY_VAT, salesUnit: p.salesUnit, salesBlock: false, ...o };
}

export const offers = {
  arlaUht1l: offer(products.arlaUht1l, {
    priceExVat: 2.57,
    comparisonPrice: 2.57,
    comparisonUnit: "L",
    availableAmount: 51,
    availableDate: REQUESTED,
    closingTime: "2026-11-15T17:00:00+02:00",
  }),
  eilaOrganic1l: offer(products.eilaOrganic1l, {
    priceExVat: 10.95,
    comparisonPrice: 2.19,
    comparisonUnit: "L",
    availableAmount: 999999,
    availableDate: REQUESTED,
    closingTime: "2026-11-12T15:00:00+02:00",
  }),
  eilaNovobox10l: offer(products.eilaNovobox10l, {
    priceExVat: 37.8, // placeholder
    comparisonPrice: 1.89,
    comparisonUnit: "L",
    availableAmount: 999999,
    availableDate: REQUESTED,
    closingTime: "2026-11-12T15:00:00+02:00",
  }),
  eila3pct1l: offer(products.eila3pct1l, {
    priceExVat: 2.05, // placeholder
    comparisonPrice: 2.05,
    comparisonUnit: "L",
    availableAmount: 9999999999,
    availableDate: REQUESTED,
    closingTime: "2026-11-15T17:00:00+02:00",
  }),
  arlaEsl10l: offer(products.arlaEsl10l, {
    priceExVat: 17.9, // placeholder
    comparisonPrice: 1.79,
    comparisonUnit: "L",
    availableAmount: 999999,
    availableDate: REQUESTED,
    closingTime: "2026-11-12T15:00:00+02:00",
  }),
} satisfies Record<keyof typeof products, Offer>;

export const chefRequest: ChefRequest = {
  text: "1,000 L lactose-free milk by Monday",
  covers: 180,
  deliveryDate: REQUESTED,
};

const lineArla: OrderLine = {
  product: products.arlaUht1l,
  offer: offers.arlaUht1l,
  quantity: 51,
  why: "51 ST: all the stock that can arrive Mon 16 Nov. The need is 1,000 L, so the rest is split to a second order.",
};

const lineEila3: OrderLine = {
  product: products.eila3pct1l,
  offer: offers.eila3pct1l,
  quantity: 950,
  why: "950 ST: the other 949 L, rounded up to full cases of 5. The only other lactose-free milk whose cut-off has not passed.",
};

/** Shown beside the split, so the passed cut-offs are visible in the table too. */
const lineEilaOrganic: OrderLine = {
  product: products.eilaOrganic1l,
  offer: offers.eilaOrganic1l,
  quantity: 0,
  why: "Not ordered: cheaper per litre and organic, but the order cut-off for Monday passed on Thu 12 Nov 15:00.",
};

const MOV_THRESHOLD = 250; // placeholder
const DELIVERY_FEE = 29; // placeholder

/** The split-order outcome: part placed at once, part waiting for a human. */
export const orders = {
  placed: {
    id: "ORD-1042",
    status: "PLACED",
    urgency: "RUNS_OUT_BEFORE_NEXT_DELIVERY",
    deliveryDate: REQUESTED,
    lines: [lineArla],
    totalExVat: 131.07,
    totalInclVat: 148.76,
    mov: { threshold: MOV_THRESHOLD, current: 131.07, deliveryFee: DELIVERY_FEE },
  },
  needsApproval: {
    id: "ORD-1043",
    status: "NEEDS_APPROVAL",
    urgency: "UNKNOWN",
    deliveryDate: REQUESTED,
    lines: [lineEila3],
    totalExVat: 1947.5,
    totalInclVat: 2210.41,
    // Same Monday delivery as ORD-1042: together they pass the threshold.
    mov: { threshold: MOV_THRESHOLD, current: 2078.57, deliveryFee: DELIVERY_FEE },
  },
} satisfies Record<string, Order>;

/** Every line the agent looked at for Monday, ordered or not. */
export const consideredLines: OrderLine[] = [lineArla, lineEila3, lineEilaOrganic];

export const approval: ApprovalRequest = {
  id: "APR-311",
  orderId: orders.needsApproval.id,
  requestedBy: "Head chef",
  createdAt: "2026-11-13T20:42:12+02:00",
  summary: "950 L Valio Eila 3 % for Monday: the rest of the 1,000 L lactose-free milk",
  lineCount: 1,
  deliveryDate: REQUESTED,
  totalExVat: orders.needsApproval.totalExVat,
  totalInclVat: orders.needsApproval.totalInclVat,
  reasons: [
    { rule: "Above the auto-approve limit", detail: "€1,947.50 ex VAT is over the €1,500.00 per-order limit." },
    {
      rule: "Substitute changes the fat %",
      detail: "3 % fat instead of 0 % in the first choice. The mandate allows 1.5 points without approval.",
    },
    {
      rule: "Stock not measured",
      detail: "Valio did not measure the stock of 463335 (it returns the unknown-stock value). The delivery may arrive short.",
    },
  ],
  status: "PENDING",
};

export const substitutes: SubstituteOption[] = [
  {
    tier: "good",
    product: products.eila3pct1l,
    offer: offers.eila3pct1l,
    recommended: true,
    tradeOffs: [
      { text: "Can still make Monday: cut-off Sun 15 Nov 17:00", direction: "plus" },
      { text: "3 % fat instead of 0 %", direction: "minus" },
      { text: "Stock not measured: may arrive short", direction: "minus" },
    ],
  },
  {
    tier: "better",
    product: products.eilaOrganic1l,
    offer: offers.eilaOrganic1l,
    tradeOffs: [
      { text: "€2.19 per L: €0.38 less than the first choice", direction: "plus" },
      { text: "Organic and Finnish swan", direction: "plus" },
      { text: "Cut-off passed Thu 12 Nov 15:00: misses Monday", direction: "minus" },
    ],
  },
  {
    tier: "best",
    product: products.eilaNovobox10l,
    offer: offers.eilaNovobox10l,
    tradeOffs: [
      { text: "Lowest price per L of the five", direction: "plus" },
      { text: "10 L novobox: less packaging, needs a dispenser", direction: "neutral" },
      { text: "Cut-off passed Thu 12 Nov 15:00: misses Monday", direction: "minus" },
    ],
  },
];

export const mandate: Mandate = {
  id: "MND-2026-11-A",
  restaurant: "Demo restaurant, Helsinki",
  signedBy: "Restaurant manager",
  validUntil: "2026-12-31",
  autoApproveLimitExVat: 1500,
  weeklyLimitExVat: 6000,
  spentThisWeekExVat: 2310.4,
  excludedAllergens: [
    { code: "AP", name: "Peanuts", presence: "CONTAINS" },
    { code: "AN", name: "Tree nuts", presence: "CONTAINS" },
    { code: "AS", name: "Sesame", presence: "MAY_CONTAIN" },
  ],
  acceptedLabels: ["EU_ORGANIC_FARMING", "GOODS_FROM_FINLAND_BLUE_SWAN", "FINNISH_HEART_SYMBOL"],
  substitutionRules: [
    { rule: "Keep the product type and lactose-free status", needsApproval: false },
    { rule: "Another pack size of the same product (1 L or 10 L)", needsApproval: false },
    { rule: "Fat % within 1.5 points of the first choice", needsApproval: false },
    { rule: "Organic instead of conventional, at most 10 % more per L", needsApproval: false },
    { rule: "Fat % more than 1.5 points away", needsApproval: true },
    { rule: "Another brand", needsApproval: true },
    { rule: "A later delivery than the chef asked for", needsApproval: true },
  ],
};

export const auditEvents: AuditEvent[] = [
  {
    id: "ev-1",
    at: "2026-11-13T20:41:02+02:00",
    kind: "request",
    actor: "chef",
    summary: "1,000 L lactose-free milk by Monday",
    reason: "180 covers on Mon 16 Nov; milk for the dessert and coffee service.",
  },
  {
    id: "ev-2",
    at: "2026-11-13T20:41:20+02:00",
    kind: "search",
    actor: "agent",
    summary: "Searched the catalog for lactose-free milk: 5 candidates",
    reason: "Kept 1 L and 10 L packs that are lactose-free; dropped flavoured drinks.",
  },
  {
    id: "ev-3",
    at: "2026-11-13T20:41:35+02:00",
    kind: "offer",
    actor: "gateway",
    summary: "Price and availability for 5 products, delivery Mon 16 Nov",
    reason:
      "462921, 463038, 464179: order cut-off Thu 12 Nov 15:00 has passed. 462775: 51 ST in stock. 463335: stock not measured.",
  },
  {
    id: "ev-4",
    at: "2026-11-13T20:41:50+02:00",
    kind: "simulate",
    actor: "gateway",
    summary: "Split: 51 ST of 462775 and 950 ST of 463335",
    reason:
      "Only 51 L of the first choice can arrive Monday. The rest comes from the only other product that can make Monday, rounded to full cases (1,001 L in all).",
  },
  {
    id: "ev-5",
    at: "2026-11-13T20:42:00+02:00",
    kind: "mandate_check",
    actor: "gateway",
    orderId: "ORD-1042",
    summary: "ORD-1042 auto-approved (€131.07 ex VAT)",
    reason: "Under the €1,500.00 auto-approve limit, and the same product the chef asked for.",
  },
  {
    id: "ev-6",
    at: "2026-11-13T20:42:05+02:00",
    kind: "order",
    actor: "gateway",
    orderId: "ORD-1042",
    summary: "ORD-1042 placed for Mon 16 Nov",
    reason: "The expected total €131.07 matched the simulate. The idempotency key was stored before the call.",
  },
  {
    id: "ev-7",
    at: "2026-11-13T20:42:10+02:00",
    kind: "mandate_check",
    actor: "gateway",
    orderId: "ORD-1043",
    summary: "ORD-1043 needs approval (€1,947.50 ex VAT)",
    reason: "Over the auto-approve limit, fat % changes by 3 points, and the stock is not measured.",
  },
  {
    id: "ev-8",
    at: "2026-11-13T20:42:12+02:00",
    kind: "approval",
    actor: "agent",
    orderId: "ORD-1043",
    summary: "Asked the buyer to approve ORD-1043",
    reason: "Waiting for a human yes to the exact total: €2,210.41 incl VAT.",
  },
];
