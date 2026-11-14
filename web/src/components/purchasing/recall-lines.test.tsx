import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApprovalCard } from "@/components/purchasing/approval-card";
import { RecallLines, recallHold } from "@/components/purchasing/recall-lines";
import { RecallPanel } from "@/components/purchasing/recall-panel";
import { coffeeApproval, coffeeOrder, coffeeRecallAlert } from "@/mocks/coffee-recall";
import type { RecallAlert } from "@/types";

const alert = coffeeRecallAlert("2026-11-14T00:30:00Z");

describe("RecallLines", () => {
  it("shows the blocked line with the notice title, date, lot, link and the replacement under it", () => {
    render(<RecallLines alerts={[alert]} />);
    const section = screen.getByRole("region", { name: "Recalls on this order" });
    expect(within(section).getByText("Blocked by recall")).toBeInTheDocument();
    expect(within(section).getByText("Suodatinkahvissa vierasesineriski")).toBeInTheDocument();
    expect(within(section).getByText("Fri 6 Mar 2026")).toBeInTheDocument();
    expect(within(section).getByText("23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 ja 5.9.2027")).toBeInTheDocument();
    expect(within(section).getByRole("link", { name: /Open the notice on ruokavirasto\.fi/ })).toHaveAttribute(
      "href",
      alert.recall.url,
    );
    expect(within(section).getByText("Replacement line")).toBeInTheDocument();
    expect(within(section).getByText(/Löfbergs Crescendo/)).toBeInTheDocument();
  });

  it("says a missing lot puts every pack in doubt, and a missing replacement keeps approval locked", () => {
    const noLot: RecallAlert = { ...alert, recall: { ...alert.recall, lot: null }, replacementLine: null };
    render(<RecallLines alerts={[noLot]} />);
    expect(screen.getByText("not stated: every pack is in doubt")).toBeInTheDocument();
    expect(screen.getByText("No replacement yet")).toBeInTheDocument();
    expect(screen.getByText(/Ideas from other brands: 12 x Löfbergs Crescendo/)).toBeInTheDocument();
  });

  it("shows a review match as a warning that does not block", () => {
    const review: RecallAlert = { ...alert, match: "review", lineStatus: "WARNING" };
    render(<RecallLines alerts={[review]} />);
    expect(screen.getByText("Recall to check")).toBeInTheDocument();
    expect(screen.queryByText("Blocked by recall")).not.toBeInTheDocument();
    expect(recallHold([review], coffeeOrder)).toBeNull();
  });
});

describe("ApprovalCard with a recall", () => {
  it("locks approval while the blocked line is still on the order", () => {
    render(<ApprovalCard request={coffeeApproval} order={coffeeOrder} recalls={[{ ...alert, replacementLine: null }]} />);
    expect(screen.getByRole("button", { name: /^Approve/ })).toBeDisabled();
    expect(screen.getByText(/is blocked by a recall\. Approval is available once the Buyer replaces/)).toBeInTheDocument();
  });

  it("lets a person approve once the line was replaced", () => {
    const replanned = { ...coffeeOrder, lines: [] as typeof coffeeOrder.lines };
    expect(recallHold([alert], replanned)).toBeNull();
  });
});

describe("RecallPanel", () => {
  it("never says the orders are clear before a check or when recalls are unknown", () => {
    const { rerender } = render(<RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: null }} onCheck={async () => { throw new Error("x"); }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Recalls not checked yet.");
    rerender(<RecallPanel status={{ kind: "unknown", message: "Could not reach the gateway." }} />);
    expect(screen.getByRole("status")).toHaveTextContent("Recalls unknown: Could not reach the gateway.");
    expect(screen.queryByText(/No recall matches/)).not.toBeInTheDocument();
    rerender(<RecallPanel status={{ kind: "unavailable" }} />);
    expect(screen.getByText(/Recall check is not available on this server yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check recalls now" })).not.toBeInTheDocument();
  });
});
