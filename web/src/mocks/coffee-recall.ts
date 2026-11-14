/**
 * The coffee recall case, from the recall monitor's recorded demo (monitor/README.md and
 * monitor/fixtures/ruokavirasto.json, scraped with Context.dev /v1/web/scrape on
 * 13 Nov 2026 22:17 UTC, 38 notices since 1 Mar 2026).
 *
 * From the recording: the notice (URL, date, title, reason, action, recalled product, lots),
 * the `possible` match on 461332 for the hotel kitchen, and the three replacement ideas from
 * another brand. From the Valio catalog: the two product codes, names, sales units and packs.
 *
 * PLACEHOLDERS: the order quantity, both prices, the stock figures, the request text and the
 * times. Replace them with the engine's answer once #358 serves the re-planned proposal.
 */
import type { ApprovalRequest, Offer, Order, OrderLine, Product, RecallAlert, RecallReplacementLine } from "@/types";

const REQUESTED = "2026-11-16";
const FOOD_VAT = 13.5;

export const coffeeProducts = {
  kultaKatriina: {
    id: "461332",
    names: {
      en: "Kulta Katriina Traditional fine ground filter coffee RAC 5x1kg",
      fi: "Kulta Katriina Perinteinen hieno jauhatus kahvi RAC 5x1kg",
    },
    brand: "Kulta Katriina",
    vendorName: "Meira Oy",
    category: "Coffee",
    salesUnit: "KI",
    baseUnit: "KG",
    baseUnitsPerSalesUnit: 5,
    units: [{ unitId: "KI", sizeInBaseUnits: 5 }],
    fatPercent: null,
    temperature: { code: 8, label: "Ambient" },
    allergens: null,
    labels: [],
    co2KgPerKg: null,
    deliveryReliability: null,
  },
  lofbergsCrescendo: {
    id: "475842",
    names: {
      en: "12 x Löfbergs Crescendo Ground Coffee 500g Rainforest Alliance",
      fi: "12 x Löfbergs Crescendo Suodatin Kahvi 500g Rainforest Alliance",
    },
    brand: "Löfbergs",
    vendorName: "Löfbergs Lila AB",
    category: "Coffee",
    salesUnit: "KI",
    baseUnit: "KG",
    baseUnitsPerSalesUnit: 6,
    units: [{ unitId: "KI", sizeInBaseUnits: 6 }],
    fatPercent: null,
    temperature: { code: 8, label: "Ambient" },
    allergens: null,
    labels: [],
    co2KgPerKg: null,
    deliveryReliability: null,
  },
} satisfies Record<string, Product>;

function coffeeOffer(product: Product, priceExVat: number, kgPerCase: number, availableAmount: number): Offer {
  return {
    productId: product.id,
    requestedDate: REQUESTED,
    priceExVat, // placeholder
    taxRatePercent: FOOD_VAT,
    comparisonPrice: Math.round((priceExVat / kgPerCase) * 100) / 100,
    comparisonUnit: "KG",
    availableAmount, // placeholder, measured (not a sentinel)
    salesUnit: product.salesUnit,
    availableDate: REQUESTED,
    closingTime: "2026-11-15T17:00:00+02:00",
    salesBlock: false,
  };
}

export const coffeeOffers = {
  kultaKatriina: coffeeOffer(coffeeProducts.kultaKatriina, 72.65, 5, 40),
  lofbergsCrescendo: coffeeOffer(coffeeProducts.lofbergsCrescendo, 64.8, 6, 25),
};

export const coffeeLine: OrderLine = {
  product: coffeeProducts.kultaKatriina,
  offer: coffeeOffers.kultaKatriina,
  quantity: 2,
  why: "2 KI (10 kg): the breakfast buffet's coffee for next week, rounded up to full cases.",
};

/** What the Buyer puts in place of the recalled line: the same 10 kg need, in 6 kg cases. */
export const coffeeReplacementLine: OrderLine = {
  product: coffeeProducts.lofbergsCrescendo,
  offer: coffeeOffers.lofbergsCrescendo,
  quantity: 2,
  why: "2 KI (12 kg): replaces the recalled Kulta Katriina; the same 10 kg need, rounded up to full 6 kg cases.",
};

export const coffeeOrder: Order = {
  id: "ORD-1045",
  status: "NEEDS_APPROVAL",
  urgency: "CAN_WAIT",
  deliveryDate: REQUESTED,
  lines: [coffeeLine],
  totalExVat: 145.3,
  totalInclVat: 164.92,
  mov: { threshold: 250, current: 145.3, deliveryFee: 29 }, // placeholders, as in the milk case
};

export const coffeeApproval: ApprovalRequest = {
  id: "APR-313",
  orderId: coffeeOrder.id,
  requestedBy: "Breakfast lead",
  createdAt: "2026-11-13T20:50:00+02:00",
  summary: "Breakfast buffet coffee for next week",
  lineCount: 1,
  deliveryDate: REQUESTED,
  totalExVat: 145.3,
  totalInclVat: 164.92,
  reasons: [{ rule: "Human approval required", detail: "Every order the Buyer proposes waits for a person." }],
  status: "PENDING",
};

/** The recorded scrape the mock answers from. */
export const coffeeRecording = {
  fetchedAt: "2026-11-13T22:17:51+00:00",
  via: "/v1/web/scrape",
  noticesScanned: 38,
};

const replacement: RecallReplacementLine = {
  productId: coffeeReplacementLine.product.id,
  productName: coffeeReplacementLine.product.names.en,
  quantity: coffeeReplacementLine.quantity,
  unit: coffeeReplacementLine.product.salesUnit,
};

/** The `possible` alert the monitor writes for the hotel, on the open coffee order. */
export function coffeeRecallAlert(detectedAt: string): RecallAlert {
  return {
    eventId: "recall-kulta-katriina-461332",
    productId: coffeeProducts.kultaKatriina.id,
    productName: coffeeProducts.kultaKatriina.names.en,
    match: "possible",
    why: "same brand Kulta Katriina, shared word(s) kahvi, perinteinen",
    where: ["in stock: 5.673 KG", "in recipes: breakfast_buffet", "on the open purchase proposal"],
    recall: {
      url: "https://www.ruokavirasto.fi/elintarvikkeet/ohjeita-kuluttajille/takaisinvedot-2023-/suodatinkahvissa-vierasesineriski/",
      date: "2026-03-06",
      title: "Suodatinkahvissa vierasesineriski",
      reason:
        "Tuotantolinjalla tapahtuneen laiterikkoontumisen vuoksi joihinkin suodatinkahvipakkauksiin on saattanut päätyä silmällä havaittavia metallipaloja.",
      action:
        "Kyseisten erien tuotteita ei tule käyttää. Kuluttajat voivat palauttaa tuotteet siihen myymälään, josta ne on ostettu; myymälä hyvittää palautetut tuotteet.",
      recalledProduct: "Kulta Katriina Perinteinen suodatinkahvi",
      brand: "Kulta Katriina",
      gtin: null,
      packageSize: "500 g",
      lot: "23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 ja 5.9.2027",
    },
    nextStep:
      "Do not use it until checked. Check your packs: only 23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 ja 5.9.2027 are recalled.",
    orderId: coffeeOrder.id,
    lineStatus: "BLOCKED_BY_RECALL",
    replacementLine: replacement,
    replacementIdeas: [
      { productId: "475842", name: "12 x Löfbergs Crescendo Ground Coffee 500g Rainforest Alliance", brand: "Löfbergs" },
      { productId: "463452", name: "12 x Löfbergs Kharisma Ground coffee 500g Rainforest Alliance", brand: "Löfbergs" },
      { productId: "468896", name: "12 x Löfbergs Magnifika Brygg Kaffe 500g Rainforest alliance", brand: "Löfbergs" },
    ],
    detectedAt,
  };
}
