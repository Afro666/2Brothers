import type { Api } from "@/api/types";
import { ApiError } from "@/api/types";
import type { LearnedFact } from "@/types";

const SAMPLE_FACTS: LearnedFact[] = [
  {
    id: "lf_demo_potato_ratio",
    kind: "CORRECTION_RATIO",
    productId: "462775",
    supplierId: null,
    name: "Washed potato 10 kg",
    value: 0.5,
    rawValue: 0.5,
    applicable: true,
    evidence: { rows: 4, from: "2026-09-21", to: "2026-11-09", last: "2026-11-09" },
    since: "2026-11-14",
    active: true,
  },
  {
    id: "lf_demo_milk_declined",
    kind: "DECLINED_PRODUCT",
    productId: "463335",
    supplierId: null,
    name: "Valio Eila lactose-free milk 1 L",
    value: 1,
    evidence: { rows: 3, from: "2026-10-03", to: "2026-11-11", last: "2026-11-11" },
    since: "2026-11-12",
    active: true,
  },
  {
    id: "lf_demo_bakery_late",
    kind: "SUPPLIER_LATE",
    productId: null,
    supplierId: "SUP-BAKERY",
    name: "Leipomo Demo",
    value: 1,
    meanDaysLate: 1,
    onTimeRate: 0.4,
    deliveries: 5,
    meanLeadTime: 3,
    sigmaLeadTime: 0.8,
    evidence: { rows: 5, from: "2026-09-28", to: "2026-11-08", last: "2026-11-08" },
    since: "2026-11-10",
    active: false,
  },
];

export function createLearnedMock(): Pick<Api, "listLearnedFacts" | "setLearnedFactActive"> {
  const facts = structuredClone(SAMPLE_FACTS);
  return {
    async listLearnedFacts() {
      return structuredClone(facts);
    },
    async setLearnedFactActive(id, active, actor) {
      if (actor !== "human") throw new ApiError("ROLE_REQUIRED", "Only an approver can switch learned facts.", {}, 403);
      if (active !== false) throw new ApiError("INVALID_REQUEST", "A learned fact can only be switched off.", {}, 422);
      const fact = facts.find((row) => row.id === id);
      if (!fact) throw new ApiError("LEARNED_FACT_NOT_FOUND", "The learned fact was not found.", {}, 404);
      fact.active = false;
      return structuredClone(fact);
    },
  };
}
