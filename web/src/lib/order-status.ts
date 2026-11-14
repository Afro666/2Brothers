import type { OrderStatus } from "@/types";

/** Statuses of an order that has already gone to the supplier; urgency no longer applies. */
export const placedStatuses = new Set<OrderStatus>(["PLACED", "NOT_SENT", "UNCONFIRMED", "SENT_READ_FAILED"]);
