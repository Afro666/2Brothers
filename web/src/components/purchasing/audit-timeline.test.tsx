import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { AuditEvent } from "@/types";

import { mapAudit } from "@/api/gateway-map";

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

  it("shows a gateway refusal as a sentence, with the refused action and the code", () => {
    const events = mapAudit([
      {
        seq: 7,
        event_id: "r1",
        kind: "refused",
        actor: "buyer-agent",
        at: "2026-11-14T10:00:00Z",
        code: "HUMAN_SESSION_REQUIRED",
        method: "POST",
        path: "/v1/kitchens/demo-kitchen/proposals/p1/approve",
      },
    ]);
    render(<AuditTimeline events={events} />);
    expect(screen.getByText("Refused by the gateway")).toBeInTheDocument();
    expect(screen.getByText("Refused: POST /v1/kitchens/demo-kitchen/proposals/p1/approve")).toBeInTheDocument();
    expect(screen.getByText("Code: HUMAN_SESSION_REQUIRED")).toBeInTheDocument();
    expect(screen.getByText("Agent")).toBeInTheDocument();
    expect(screen.queryByText("refused")).toBeNull();
  });
});
