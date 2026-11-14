import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";
import { renderApp } from "@/test/render";

function coffeeCard() {
  return screen.getByText("Breakfast buffet coffee for next week").closest('[data-slot="card"]') as HTMLElement;
}

function replacementCard() {
  return screen.getByText("Replacement coffee for the recalled breakfast order").closest('[data-slot="card"]') as HTMLElement;
}

describe("ApprovalsPage recalls", () => {
  beforeEach(() => localStorage.clear());

  it("checks recalls, holds the coffee and adds a separate approvable replacement order", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/approvals", api);

    const panel = await screen.findByRole("region", { name: "Food recalls" });
    expect(within(panel).getByRole("status")).toHaveTextContent("Recalls not checked yet.");
    expect(within(coffeeCard()).getByRole("button", { name: /Approve €164\.92 incl VAT/ })).toBeEnabled();

    await user.click(within(panel).getByRole("button", { name: "Check recalls now" }));

    expect(await within(panel).findByText("1 recall affects your open order")).toBeInTheDocument();
    expect(within(panel).getByText(/Powered by Context\.dev/)).toHaveTextContent("Powered by Context.dev /v1/web/scrape");
    expect(within(panel).getByText(/Checked 38 Ruokavirasto notices/)).toBeInTheDocument();

    const card = coffeeCard();
    expect(await within(card).findByText("Blocked by recall")).toBeInTheDocument();
    expect(within(card).getByText("Suodatinkahvissa vierasesineriski")).toBeInTheDocument();
    expect(within(card).getByText("Replacement order")).toBeInTheDocument();
    expect(within(card).getByText("Blocked by a recall. This proposal cannot be approved as it is.")).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: /^Approve/ })).not.toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Reject" })).toBeEnabled();
    expect(within(card).getByRole("link", { name: /Review replacement order/ })).toHaveAttribute(
      "href",
      "#proposal-ORD-1045-R",
    );
    const replacement = replacementCard();
    expect(replacement).toHaveAttribute("id", "proposal-ORD-1045-R");
    expect(replacement).toHaveAttribute("tabindex", "-1");
    expect(await within(replacement).findByRole("button", { name: /Approve €147\.10 incl VAT/ })).toBeEnabled();
    await user.click(within(card).getByRole("link", { name: /Review replacement order/ }));
    expect(replacement).toHaveFocus();
    expect((await api.getOrder("ORD-1045")).lines.map((line) => line.product.id)).toEqual(["461332"]);
    expect((await api.getOrder("ORD-1045-R")).lines.map((line) => line.product.id)).toEqual(["475842"]);

    await waitFor(async () => {
      const events = await api.listAudit({ orderId: "ORD-1045" });
      expect(events.at(-1)?.summary).toMatch(/^Blocked 461332 by recall; replaced with 475842/);
    });
  });

  it("keeps held proposals between the waiting and decided groups without counting them as waiting", async () => {
    const api = createMockApi();
    await api.checkRecalls!("human");
    await api.approve(
      { approvalId: "APR-313-R", approvalRef: "APR-313-R", expectedTotalExVat: 129.6, expectedTotalInclVat: 147.1 },
      "human",
    );
    renderApp("/approvals", api);

    const waiting = (await screen.findByRole("heading", { name: "Waiting for you (3)" })).closest("section") as HTMLElement;
    const held = screen.getByRole("heading", { name: "Held by a recall (1)" }).closest("section") as HTMLElement;
    const decided = screen.getByRole("heading", { name: "Decided" }).closest("section") as HTMLElement;
    expect(within(waiting).queryByText("Breakfast buffet coffee for next week")).not.toBeInTheDocument();
    expect(within(held).getByText("Breakfast buffet coffee for next week")).toBeInTheDocument();
    expect(within(held).queryByText("Replacement coffee for the recalled breakfast order")).not.toBeInTheDocument();
    expect(within(decided).getByText("Replacement coffee for the recalled breakfast order")).toBeInTheDocument();
    expect(waiting.compareDocumentPosition(held)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    expect(held.compareDocumentPosition(decided)).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
  });

  it("is a replay when checked twice: one alert and one replacement proposal", async () => {
    const api = createMockApi();
    await api.checkRecalls!("human");
    const second = await api.checkRecalls!("human");
    expect(second.alerts).toHaveLength(1);
    expect((await api.getOrder("ORD-1045")).lines.map((line) => line.product.id)).toEqual(["461332"]);
    expect((await api.listApprovals()).filter((row) => row.orderId === "ORD-1045-R")).toHaveLength(1);
    const replans = (await api.listAudit({ orderId: "ORD-1045" })).filter((event) => event.summary.startsWith("Blocked"));
    expect(replans).toHaveLength(1);
  });

  it("approves the replacement with its own total while the held proposal stays blocked", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    await api.checkRecalls!("human");
    const approve = vi.spyOn(api, "approve");
    renderApp("/approvals", api);

    expect(await screen.findByText("Replacement coffee for the recalled breakfast order")).toBeInTheDocument();
    const replacement = replacementCard();
    await user.click(within(replacement).getByRole("button", { name: /Approve €147\.10 incl VAT/ }));

    const dialog = await screen.findByRole("dialog", { name: "Approve this order?" });
    expect(dialog).toHaveTextContent("You approve exactly €129.60 ex VAT (€147.10 incl VAT).");
    await user.click(within(dialog).getByRole("button", { name: "Yes, approve €147.10" }));

    await waitFor(() => {
      expect(approve).toHaveBeenCalledWith(
        { approvalId: "APR-313-R", approvalRef: "APR-313-R", expectedTotalExVat: 129.6, expectedTotalInclVat: 147.1 },
        "human",
      );
    });
    expect(approve).toHaveBeenCalledTimes(1);
    expect((await api.getApproval("APR-313-R")).status).toBe("APPROVED");
    expect(await within(replacementCard()).findByText(/Approved: €129\.60 ex VAT, €147\.10 incl VAT/)).toBeInTheDocument();
    expect((await api.getApproval("APR-313")).status).toBe("BLOCKED_BY_RECALL");
    expect(within(coffeeCard()).queryByRole("button", { name: /^Approve/ })).not.toBeInTheDocument();
  });

  it("does not hold or replace a decided order", async () => {
    const api = createMockApi();
    await api.reject("APR-313", "not needed", "human");
    const result = await api.checkRecalls!("human");
    expect(result.alerts[0]).toMatchObject({ orderId: null, replacement: null });
    expect((await api.getOrder("ORD-1045")).lines.map((line) => line.product.id)).toEqual(["461332"]);
    expect((await api.listApprovals()).some((row) => row.orderId === "ORD-1045-R")).toBe(false);
  });

  it("refuses direct approval of a held order while allowing its rejection", async () => {
    const api = createMockApi();
    await api.checkRecalls!("human");
    await expect(
      api.approve({ approvalId: "APR-313", approvalRef: "APR-313", expectedTotalExVat: 145.3, expectedTotalInclVat: 164.92 }, "human"),
    ).rejects.toMatchObject({ code: "BLOCKED_BY_RECALL", message: expect.stringContaining("blocked by a recall") });
    expect((await api.reject("APR-313", "Recalled line; replacement proposed", "human")).status).toBe("REJECTED");
    expect((await api.getApproval("APR-313-R")).status).toBe("PENDING");
  });

  it("rejects a held card from the inbox and moves it to Decided", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    await api.checkRecalls!("human");
    const reject = vi.spyOn(api, "reject");
    renderApp("/approvals", api);

    const held = (await screen.findByRole("heading", { name: "Held by a recall (1)" })).closest("section") as HTMLElement;
    const card = within(held).getByText("Breakfast buffet coffee for next week").closest('[data-slot="card"]') as HTMLElement;
    expect(within(card).queryByRole("button", { name: /^Approve/ })).not.toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Reject" }));

    const dialog = await screen.findByRole("dialog", { name: "Reject this order?" });
    await user.type(within(dialog).getByLabelText("Reason (optional)"), "Recalled line; replacement proposed");
    await user.click(within(dialog).getByRole("button", { name: "Reject" }));

    await waitFor(() => expect(reject).toHaveBeenCalledWith("APR-313", "Recalled line; replacement proposed", "human"));
    expect((await api.getApproval("APR-313")).status).toBe("REJECTED");
    await waitFor(() => expect(screen.queryByRole("heading", { name: /Held by a recall/ })).not.toBeInTheDocument());
    const decided = screen.getByRole("heading", { name: "Decided" }).closest("section") as HTMLElement;
    expect(within(decided).getByText("Breakfast buffet coffee for next week")).toBeInTheDocument();
    expect(within(decided).getByText("Rejected. This order will not be sent.")).toBeInTheDocument();
  });

  it("rejects a held proposal through the gateway's reject route", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify({ status: "rejected" }), { status: 200, headers: { "content-type": "application/json" } }));
    vi.stubGlobal("fetch", fetch);
    const api = createHttpApi("http://gateway.test");
    // Only the first call matters here: the reject POST. The re-read after it is answered with a stub.
    await api.reject("APR-313", "Recalled line", "human").catch(() => undefined);
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(String(url)).toMatch(/\/proposals\/.+\/reject$/);
    expect(init.method).toBe("POST");
    vi.unstubAllGlobals();
  });

  it("says recalls are unknown when loading them fails", async () => {
    const api = createMockApi();
    api.listRecalls = async () => {
      throw new ApiError("NETWORK", "Could not reach the gateway.");
    };
    renderApp("/approvals", api);
    const panel = await screen.findByRole("region", { name: "Food recalls" });
    expect(await within(panel).findByText(/Recalls unknown: Could not reach the gateway\./)).toBeInTheDocument();
  });

  it("uses the real recall methods in gateway mode instead of saying they are unavailable", async () => {
    const api = createHttpApi("http://gateway.test");
    api.listRecalls = async () => ({ lastCheck: null, alerts: [] });
    api.getSession = createMockApi().getSession;
    renderApp("/approvals", api);
    const panel = await screen.findByRole("region", { name: "Food recalls" });
    expect(within(panel).getByText("Recalls not checked yet.")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Check recalls now" })).toBeInTheDocument();
    expect(api.live).toEqual(expect.objectContaining(new Set()));
    expect(api.live!.has("listRecalls")).toBe(true);
    expect(api.live!.has("checkRecalls")).toBe(true);
  });
});
