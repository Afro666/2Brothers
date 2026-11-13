import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";

import { RiskBadge } from "./risk-badge";

describe("RiskBadge", () => {
  it.each([
    ["SHORT", "Short"],
    ["AT_RISK", "At risk"],
    ["COVERED", "Covered"],
    ["UNKNOWN", "Unknown: check stock"],
  ] as const)("shows %s as %s", (risk, label) => {
    render(
      <TooltipProvider>
        <RiskBadge risk={risk} />
      </TooltipProvider>,
    );
    expect(screen.getByText(label)).toHaveAttribute("data-risk", risk);
  });
});
