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

  it("renders plain-English labels for the kinds added on 14 Nov and for tool steps", () => {
    const events = mapAudit([
      { seq: 1, event_id: "a", kind: "stock_photo_read", actor: "chef", at: "2026-11-14T10:00:00Z" },
      { seq: 2, event_id: "b", kind: "demo_inbox_cleared", actor: "chef", at: "2026-11-14T10:01:00Z" },
      { event_id: "c", tool: "request_approval", type: "tool_call_started", arguments: {} },
    ]);
    render(<AuditTimeline events={events} />);
    expect(screen.getByText("Shelf photo read by Nemotron VL")).toBeInTheDocument();
    expect(screen.getByText("Test proposals cleared before a demo")).toBeInTheDocument();
    expect(screen.getByText("Buyer asked for approval")).toBeInTheDocument();
    expect(screen.queryByText("stock_photo_read")).not.toBeInTheDocument();
  });
});
