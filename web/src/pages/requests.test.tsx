import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

async function ask(api = createMockApi()) {
  const user = userEvent.setup();
  renderApp("/requests", api);
  await screen.findByRole("heading", { level: 1, name: "Request an order" });
  await user.type(screen.getByLabelText("What do you need?"), "1,000 L lactose-free milk by Monday");
  await user.type(screen.getByLabelText("Needed by"), "2026-11-16");
  await user.click(screen.getByRole("button", { name: "Ask the agent" }));
  return user;
}

describe("RequestsPage", () => {
  beforeEach(() => localStorage.clear());

  it("fills the box from an example chip and never sends it (#1142)", async () => {
    const api = createMockApi();
    let asked = 0;
    const original = api.submitChefRequest.bind(api);
    api.submitChefRequest = async (request) => {
      asked += 1;
      return original(request);
    };
    const user = userEvent.setup();
    renderApp("/requests", api);
    await screen.findByRole("heading", { level: 1, name: "Request an order" });
    const examples = screen.getByRole("group", { name: "Examples" });
    await user.click(within(examples).getByRole("button", { name: "15 kg peanut butter" }));
    expect(screen.getByLabelText("What do you need?")).toHaveValue("15 kg peanut butter");
    await user.click(within(examples).getByRole("button", { name: "50 kg cheese by Monday" }));
    expect(screen.getByLabelText("What do you need?")).toHaveValue("50 kg cheese by Monday");
    expect(screen.queryByRole("region", { name: "Proposal" })).not.toBeInTheDocument();
    expect(asked).toBe(0);
  });

  it("shows the proposal with the line's why and the approvals link", async () => {
    const user = await ask();

    const proposal = await screen.findByRole("region", { name: "Proposal" });
    expect(within(proposal).getByRole("heading", { level: 2 })).toHaveTextContent(
      'Proposal for "1,000 L lactose-free milk by Monday"',
    );
    expect(within(proposal).getAllByText(/the other 949 L, rounded up to full cases of 5/).length).toBeGreaterThan(0);
    expect(within(proposal).getByRole("heading", { name: "Other options" })).toBeInTheDocument();
    expect(within(proposal).getByRole("link", { name: /To approve/ })).toHaveAttribute("href", "/approvals");
    await user.click(within(proposal).getByRole("button", { name: "Use good" }));
    expect(within(proposal).getByRole("status")).toHaveTextContent(
      "Noted: you prefer Valio Eila 3 % lactose free milk drink 1 L. This is not applied to the order yet; tell the approver, or ask the Buyer again.",
    );
  });

  it("badges cut-off options as missing the date, not Better or Best", async () => {
    await ask();

    const proposal = await screen.findByRole("region", { name: "Proposal" });
    await within(proposal).findByRole("heading", { name: "Other options" });
    expect(within(proposal).getAllByText("Misses the date")).toHaveLength(2);
    expect(within(proposal).getAllByRole("button", { name: "Cannot make this delivery" })).toHaveLength(2);
    expect(within(proposal).queryByText("Better")).not.toBeInTheDocument();
    expect(within(proposal).queryByText("Best")).not.toBeInTheDocument();
    expect(within(proposal).getByText("Good")).toBeInTheDocument();
  });

  it("keeps the typed text when the gateway cannot be reached", async () => {
    const failing = {
      ...createMockApi(),
      submitChefRequest: async () => {
        throw new ApiError("NETWORK", "Could not reach the gateway.");
      },
    };
    await ask(failing);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the gateway.");
    expect(screen.getByLabelText("What do you need?")).toHaveValue("1,000 L lactose-free milk by Monday");
  });
});
