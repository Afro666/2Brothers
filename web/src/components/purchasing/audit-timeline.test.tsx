import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

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

  it("says which account took a step, when the step has one", () => {
    const step = { id: "e1", at: "2026-11-14T10:00:00Z", kind: "order", summary: "Order placed", reason: "expected_total: 173.76" };
    render(
      <AuditTimeline
        events={[
          { ...step, actor: "human", actorName: "approver@example.test" },
          { ...step, id: "e2", actor: "agent" },
        ] as AuditEvent[]}
      />,
    );
    expect(screen.getByText("By approver@example.test")).toBeInTheDocument();
    expect(screen.getAllByText(/^By /)).toHaveLength(1);
  });
});
