import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createHttpApi } from "@/api/http";
import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";
import { renderApp } from "@/test/render";

function coffeeCard() {
  return screen.getByText("Breakfast buffet coffee for next week").closest('[data-slot="card"]') as HTMLElement;
}

describe("ApprovalsPage recalls", () => {
  beforeEach(() => localStorage.clear());

  it("checks recalls, shows the banner, blocks the coffee line and puts the replacement in the total", async () => {
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
    expect(within(card).getByText("Replacement line")).toBeInTheDocument();
    // 2 KI Löfbergs at the placeholder €64.80, 13.5 % VAT: the re-planned exact total.
    expect(await within(card).findByRole("button", { name: /Approve €147\.10 incl VAT/ })).toBeEnabled();

    await waitFor(async () => {
      const events = await api.listAudit({ orderId: "ORD-1045" });
      expect(events.at(-1)?.summary).toMatch(/^Blocked 461332 by recall; replaced with 475842/);
    });
  });

  it("is a replay when checked twice: one alert, one re-plan", async () => {
    const api = createMockApi();
    await api.checkRecalls!("human");
    const second = await api.checkRecalls!("human");
    expect(second.alerts).toHaveLength(1);
    expect((await api.getOrder("ORD-1045")).lines.map((line) => line.product.id)).toEqual(["475842"]);
    const replans = (await api.listAudit({ orderId: "ORD-1045" })).filter((event) => event.summary.startsWith("Blocked"));
    expect(replans).toHaveLength(1);
  });

  it("does not re-plan a decided order", async () => {
    const api = createMockApi();
    await api.reject("APR-313", "not needed", "human");
    const result = await api.checkRecalls!("human");
    expect(result.alerts[0]).toMatchObject({ orderId: null, replacementLine: null });
    expect((await api.getOrder("ORD-1045")).lines.map((line) => line.product.id)).toEqual(["461332"]);
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

  it("says the check is not available on a gateway that does not serve it", async () => {
    const api = createHttpApi("http://gateway.test");
    api.getSession = createMockApi().getSession;
    renderApp("/approvals", api);
    expect(await screen.findByText(/Recall check is not available on this server yet/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Check recalls now" })).not.toBeInTheDocument();
  });
});
