import type { ApprovalRequest, AuditEvent, Order } from "@/types";

export interface KitchenExportData {
  orders: Order[];
  proposals: ApprovalRequest[];
  audit: AuditEvent[];
}

export function csvCell(value: unknown): string {
  let text = value == null ? "unknown" : typeof value === "string" ? value : JSON.stringify(value);
  if (/^(?:[\t\r]|[\s\u0000-\u001f\u007f-\u009f]*[=+\-@])/.test(text)) text = `'${text}`;
  return `"${text.replaceAll('"', '""')}"`;
}

export function kitchenExportCsv(data: KitchenExportData): string {
  const records = [
    ...data.orders.map((order) => ["order", order.id, null, order.status, "", order]),
    ...data.proposals.map((proposal) => ["proposal", proposal.id, proposal.createdAt, proposal.status, proposal.summary, proposal]),
    ...data.audit.map((event) => ["audit", event.id, event.at, "", event.summary, event]),
  ];
  return [
    ["record_type", "id", "at", "status", "summary", "data"],
    ...records,
  ].map((row) => row.map(csvCell).join(",")).join("\r\n");
}

export function downloadKitchenExport(format: "json" | "csv", data: KitchenExportData, now = new Date()): void {
  const text = format === "json" ? JSON.stringify(data, null, 2) : kitchenExportCsv(data);
  const blob = new Blob([text], { type: format === "json" ? "application/json;charset=utf-8" : "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `kitchen-export-${now.toISOString().slice(0, 10)}.${format}`;
  anchor.style.display = "none";
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
