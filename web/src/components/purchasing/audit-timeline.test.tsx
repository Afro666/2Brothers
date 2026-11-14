import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mapAudit } from "@/api/gateway-map";
import type { AuditEvent } from "@/types";

import { AuditTimeline } from "./audit-timeline";

describe("AuditTimeline", () => {
  it("shows the raw kind and actor when the app does not know them", () => {
    const event = {
      id: "e1",
      at: "2026-11-14T10:00:00Z",
      kind: "tool_call",
      actor: "mcp_client",
      summary: "Called search_products",
      reason: "Agent looked for milk",
    } as unknown as AuditEvent;
    render(<AuditTimeline events={[event]} />);
    expect(screen.getByText("tool_call")).toBeInTheDocument();
    expect(screen.getByText("mcp_client")).toBeInTheDocument();
    expect(screen.getByText("Called search_products")).toBeInTheDocument();
  });

  it("renders the gateway's newer kinds and tool steps in plain English; an unknown kind stays raw", () => {
    const at = "2026-11-14T10:00:00+00:00";
    const kinds = [
      "stock_photo_read",
      "audit_demo_tamper",
      "audit_demo_restore",
      "option_chosen",
      "order_lookup",
      "order_resolved",
      "recall_check",
      "demo_inbox_cleared",
      "brand_new_kind",
    ];
    const events = mapAudit([
      ...kinds.map((kind, i) => ({ event_id: `k${i}`, kind, actor: "aron", at })),
      { event_id: "t1", tool: "request_approval", type: "tool_call_started", arguments: {} },
      { event_id: "t2", tool: "simulate_order", type: "tool_call_finished", result: { ok: true } },
      { event_id: "t3", tool: "mystery_tool", type: "tool_call_finished", result: { ok: true } },
    ]);
    render(<AuditTimeline events={events} />);
    for (const label of [
      "Shelf photo read by Nemotron VL",
      "Tamper demo: a line was changed",
      "Tamper demo: the line was restored",
      "A person chose an option",
      "A person looked up an order with an unknown send result",
      "A person resolved an unknown send",
      "Recall check",
      "Test proposals cleared before a demo",
      "brand_new_kind",
      "Buyer asked for approval",
      "Buyer simulated the order",
      "mystery_tool finished",
    ]) {
      expect(screen.getByText(label)).toBeInTheDocument();
    }
  });
});
