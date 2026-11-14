import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ApprovalCard } from "@/components/purchasing/approval-card";
import { RecallLines, recallHold } from "@/components/purchasing/recall-lines";
import { RecallPanel } from "@/components/purchasing/recall-panel";
import { coffeeApproval, coffeeOrder, coffeeRecallAlert, coffeeReplacementOrder } from "@/mocks/coffee-recall";
import type { RecallAlert, RecallCheck } from "@/types";

const alert = coffeeRecallAlert("2026-11-14T00:30:00Z");

describe("RecallLines", () => {
  it("shows the notice and the separate replacement order with its own total and card link", () => {
    render(<RecallLines alerts={[alert]} />);
    const section = screen.getByRole("region", { name: "Recalls on this order" });
    expect(within(section).getByText("Blocked by recall")).toBeInTheDocument();
    expect(within(section).getByText("Suodatinkahvissa vierasesineriski")).toBeInTheDocument();
    expect(within(section).getByText("Fri 6 Mar 2026")).toBeInTheDocument();
    expect(within(section).getByText("23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 ja 5.9.2027")).toBeInTheDocument();
    expect(within(section).getByRole("link", { name: /Open the notice \(www\.ruokavirasto\.fi\)/ })).toHaveAttribute(
      "href",
      alert.recall.url,
    );
    expect(within(section).getByRole("link", { name: /Open the notice \(www\.ruokavirasto\.fi\)/ })).toHaveAttribute(
      "target",
      "_blank",
    );
    expect(within(section).getByRole("link", { name: /Open the notice \(www\.ruokavirasto\.fi\)/ })).toHaveAttribute(
      "rel",
      "noopener noreferrer",
    );
    expect(within(section).getByText("Replacement order")).toBeInTheDocument();
    expect(within(section).getByText(/Löfbergs Crescendo/)).toBeInTheDocument();
    expect(within(section).getByText(/Separate order total:/)).toHaveTextContent("€147.10 incl VAT");
    const link = within(section).getByRole("link", { name: /Review replacement order/ });
    expect(link).toHaveAttribute("href", "#proposal-ORD-1045-R");
  });

  it.each([
    ["https://ruokavirasto.fi@evil.example/x", "evil.example"],
    ["https://foodsupplier.example/notice", "foodsupplier.example"],
  ])("uses only the actual notice hostname in the link label: %s", (url, hostname) => {
    render(<RecallLines alerts={[{ ...alert, recall: { ...alert.recall, url } }]} />);
    expect(screen.getByRole("link", { name: new RegExp(`Open the notice \\(${hostname}\\)`) })).toHaveAttribute(
      "href",
      url,
    );
    expect(screen.queryByRole("link", { name: /Open the notice on ruokavirasto\.fi/ })).not.toBeInTheDocument();
  });

  it("shows an unknown source as plain text without a link", () => {
    render(<RecallLines alerts={[{ ...alert, recall: { ...alert.recall, url: null } }]} />);
    expect(screen.getByText("source unknown")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open the notice/ })).not.toBeInTheDocument();
  });

  it.each(["javascript:alert(1)", "http://www.ruokavirasto.fi/x", "https://"])(
    "shows a non-https or malformed notice URL as plain text without a link: %s",
    (url) => {
      render(<RecallLines alerts={[{ ...alert, recall: { ...alert.recall, url } }]} />);
      expect(screen.getByText("source unknown")).toBeInTheDocument();
      expect(screen.queryByRole("link", { name: /Open the notice/ })).not.toBeInTheDocument();
    },
  );

  it("says a missing lot puts every pack in doubt, and a failed re-plan keeps approval locked", () => {
    const noLot: RecallAlert = {
      ...alert,
      recall: { ...alert.recall, lot: null },
      replacement: null,
      replanError: "NO_SAFE_REPLACEMENT",
    };
    render(<RecallLines alerts={[noLot]} />);
    expect(screen.getByText("not stated: every pack is in doubt")).toBeInTheDocument();
    expect(screen.getByText("The replacement order could not be made.")).toBeInTheDocument();
    expect(screen.getByText(/No safe replacement was found\. Approval of the held order stays locked/)).toBeInTheDocument();
    expect(screen.getByText(/Ideas from other brands: 12 x Löfbergs Crescendo/)).toBeInTheDocument();
  });

  it("reports an absent replacement neutrally when there is no re-plan error", () => {
    render(<RecallLines alerts={[{ ...alert, replacement: null, replanError: null }]} />);
    expect(screen.getByText("No replacement order has been proposed.")).toBeInTheDocument();
    expect(screen.getByText("No replacement order has been proposed.").parentElement).toHaveClass("bg-muted");
    expect(screen.getByText("Approval of the held order stays locked.")).toBeInTheDocument();
    expect(screen.queryByText(/replacement order could not be made|replacement order could not be read/)).not.toBeInTheDocument();
  });

  it.each([
    ["KITCHEN_POLICY_UNKNOWN", "The kitchen's allergen policy is unknown"],
    ["REPLACEMENT_SHORTFALL", "A replacement could not cover the full quantity"],
    ["REPLACEMENT_UNAVAILABLE", "The replacement is unavailable"],
    ["A_FUTURE_ERROR", "The replacement order could not be prepared"],
  ])("explains re-plan error %s without exposing the code", (replanError, message) => {
    render(<RecallLines alerts={[{ ...alert, replacement: null, replanError }]} />);
    expect(screen.getByText(new RegExp(message))).toBeInTheDocument();
    expect(screen.queryByText(new RegExp(replanError))).not.toBeInTheDocument();
  });

  it("keeps a dismissed alert's hold and shows who dismissed it and why", () => {
    const dismissed: RecallAlert = {
      ...alert,
      status: "dismissed",
      dismissedBy: "chef@example.test",
      dismissedAt: "2026-11-14T05:00:00Z",
      dismissReason: "The affected lot is not held here.",
    };
    render(<RecallLines alerts={[dismissed]} />);
    expect(screen.getByText("Dismissed by chef@example.test: The affected lot is not held here.")).toBeInTheDocument();
    expect(screen.getByText("Blocked by recall")).toBeInTheDocument();
    expect(recallHold([dismissed], coffeeOrder)).toMatch(/This order cannot be approved/);
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
    render(<ApprovalCard request={coffeeApproval} order={coffeeOrder} recalls={[alert]} />);
    expect(screen.getByRole("button", { name: /^Approve/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
    expect(screen.getByText(/is blocked by a recall\. This order cannot be approved/)).toBeInTheDocument();
    expect(screen.getByText(/approve the replacement order instead/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Review replacement order/ })).toBeInTheDocument();
  });

  it("does not suggest a replacement in the hold message when none is proposed", () => {
    render(
      <ApprovalCard
        request={coffeeApproval}
        order={coffeeOrder}
        recalls={[{ ...alert, replacement: null, replanError: "NO_SAFE_REPLACEMENT" }]}
      />,
    );
    expect(screen.getByText(/No replacement is proposed yet\. You can reject this order\./)).toBeInTheDocument();
    expect(screen.queryByText(/approve the replacement order instead/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Review replacement order/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Approve/ })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("does not put the original alert on the separate replacement order", () => {
    expect(recallHold([alert], coffeeReplacementOrder)).toBeNull();
  });
});

const check: RecallCheck = {
  checkedAt: "2026-11-14T04:30:00+00:00",
  checkedBy: "chef@example.test",
  source: "recording",
  liveError: "NO_KEY",
  fetchedAt: "2026-11-13T22:17:51+00:00",
  detailsFetchedAt: "2026-11-13T22:17:51+00:00",
  via: "Context.dev /v1/web/scrape (json)",
  noticesScanned: 38,
  noticesListed: null,
  noticesUnread: null,
  scannedSince: "2026-03-02",
};

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

  it.each([
    ["NO_KEY", "Context.dev key is not set on this server"],
    ["TIMEOUT", "Context.dev was too slow"],
    ["UPSTREAM_ERROR", "Context.dev could not be read"],
    ["BAD_ANSWER", "Context.dev could not be read"],
  ] as const)("explains why the recording was used: %s", (liveError, message) => {
    render(<RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: { ...check, liveError } }} />);
    expect(screen.getByText(new RegExp(message))).toBeInTheDocument();
    expect(screen.getByText(/Powered by Context.dev/)).toHaveTextContent("Powered by Context.dev /v1/web/scrape");
  });

  it.each([
    ["https://www.ruokavirasto.fi/notice", true],
    ["javascript:alert(1)", false],
    ["http://www.ruokavirasto.fi/notice", false],
  ])("links an unheld recall's notice title only when its URL is https: %s", (url, linked) => {
    const unheld = { ...alert, recall: { ...alert.recall, url, title: "Notice title" } };
    render(<RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: check, unheld: [unheld] }} />);
    const list = screen.getByRole("list", { name: "Recalled products in your kitchen" });
    if (linked) {
      expect(within(list).getByRole("link", { name: /Notice title/ })).toHaveAttribute("href", url);
    } else {
      expect(within(list).queryByRole("link")).not.toBeInTheDocument();
      expect(within(list).getByText(/Notice title/)).toBeInTheDocument();
    }
  });

  it("does not report a Context.dev failure for a recording without a live error", () => {
    render(<RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: { ...check, liveError: null } }} />);
    expect(screen.getByText(/Shown from the recording\./)).toBeInTheDocument();
    expect(screen.queryByText(/Context.dev could not be read/)).not.toBeInTheDocument();
  });

  it("reports a live list count and warns about unread notices instead of claiming no matches", () => {
    render(
      <RecallPanel
        status={{
          kind: "ready",
          affecting: 0,
          lastCheck: { ...check, source: "live", liveError: null, noticesListed: 102, noticesUnread: 2 },
        }}
      />,
    );
    const panel = screen.getByRole("region", { name: "Food recalls" });
    expect(panel).toHaveClass("bg-warning-surface");
    expect(screen.getByRole("status")).toHaveTextContent("2 new notices not read yet");
    expect(screen.getByText(/Scraped live: 102 notices on the list/)).toBeInTheDocument();
    expect(screen.queryByText(/No recall matches/)).not.toBeInTheDocument();
  });

  it("warns about unread notices in a recording instead of claiming no matches", () => {
    render(<RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: { ...check, noticesUnread: 3 } }} />);
    const panel = screen.getByRole("region", { name: "Food recalls" });
    expect(panel).toHaveClass("bg-warning-surface");
    expect(screen.getByRole("status")).toHaveTextContent("3 new notices not read yet");
    expect(screen.getByText(/From the recorded scrape/)).toBeInTheDocument();
    expect(screen.queryByText(/No recall matches/)).not.toBeInTheDocument();
  });
});
