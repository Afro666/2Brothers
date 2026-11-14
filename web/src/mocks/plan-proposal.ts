/**
 * A mock menu-plan proposal as the approvals inbox shows it (#800): "Propose order for this
 * week" in mock mode adds one PENDING approval and its order, as the gateway does. Sample
 * prices include 14 % VAT; stock is "unknown", so the supplier confirms after a yes.
 */
import type { PlannedProposal } from "@/api/mock-planning";
import type { ApprovalRequest, Order, OrderLine } from "@/types";

const VAT_RATE = 14;
const UNKNOWN_STOCK = 999999;

const round2 = (value: number) => Math.round((value + Number.EPSILON) * 100) / 100;
const exVat = (value: number) => value / (1 + VAT_RATE / 100);

export function planProposalCase({ proposal, from, to, requestedDate, lines }: PlannedProposal): {
  order: Order;
  approval: ApprovalRequest;
} {
  const orderLines: OrderLine[] = lines.map((line) => ({
    product: {
      id: line.productId,
      names: { en: line.productName, fi: line.productName },
      brand: "Sample data",
      vendorName: "Sample data",
      category: "Menu plan",
      salesUnit: line.unit,
      baseUnit: line.unit,
      baseUnitsPerSalesUnit: null,
      units: [{ unitId: line.unit, sizeInBaseUnits: 1 }],
      fatPercent: null,
      temperature: null,
      allergens: [],
      labels: [],
      co2KgPerKg: null,
      deliveryReliability: null,
    },
    offer: {
      productId: line.productId,
      requestedDate,
      priceExVat: round2(exVat(line.priceInclVat)),
      taxRatePercent: VAT_RATE,
      comparisonPrice: null,
      comparisonUnit: null,
      availableAmount: UNKNOWN_STOCK,
      salesUnit: line.unit,
      availableDate: requestedDate,
      closingTime: null,
      salesBlock: false,
    },
    quantity: line.quantity,
    lineTotal: round2(exVat(line.quantity * line.priceInclVat)),
    why: `${line.quantity} ${line.unit} for the menu plan ${from} to ${to}, net of counted stock.`,
  }));
  const totalExVat = round2(exVat(proposal.totalInclVat));
  const order: Order = {
    id: `ORD-${proposal.id}`,
    status: "NEEDS_APPROVAL",
    urgency: "UNKNOWN",
    deliveryDate: requestedDate,
    lines: orderLines,
    supplierMustConfirm: [],
    totalExVat,
    vat: round2(proposal.totalInclVat - totalExVat),
    deliveryFee: null,
    totalInclVat: proposal.totalInclVat,
    mov: null,
  };
  const approval: ApprovalRequest = {
    id: `APR-${proposal.id}`,
    approvalRef: `APR-${proposal.id}`,
    orderId: order.id,
    requestedBy: "Head chef",
    createdAt: new Date().toISOString(),
    summary: `Menu plan ${from} to ${to}: ${proposal.lineCount} ${proposal.lineCount === 1 ? "line" : "lines"}`,
    lineCount: proposal.lineCount,
    deliveryDate: requestedDate,
    totalExVat,
    totalInclVat: proposal.totalInclVat,
    reasons: [],
    suppliersToConfirm: [],
    status: "PENDING",
  };
  return { order, approval };
}
