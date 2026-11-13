import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuditTimeline } from "@/components/purchasing/audit-timeline";
import type { AuditEvent } from "@/types";

describe("AuditTimeline", () => {
  it("renders an unknown kind and actor with fallback labels", () => {
    const event = {
      id: "evt-unknown",
      at: "2026-11-13T10:00:00Z",
      kind: "tool_call",
      actor: "nemotron",
      summary: "Called search_products",
      reason: "Looking for milk",
    } as unknown as AuditEvent;
    render(<AuditTimeline events={[event]} />);

    expect(screen.getByText("tool_call")).toBeInTheDocument();
    expect(screen.getByText("nemotron")).toBeInTheDocument();
    expect(screen.getByText("Called search_products")).toBeInTheDocument();
  });
});
