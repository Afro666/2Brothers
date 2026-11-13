import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

async function ask(api = createMockApi()) {
  const user = userEvent.setup();
  renderApp("/requests", api);
  await screen.findByRole("heading", { level: 1, name: "Requests" });
  await user.type(screen.getByLabelText("What do you need?"), "1,000 L lactose-free milk by Monday");
  await user.type(screen.getByLabelText("Needed by"), "2026-11-16");
  await user.click(screen.getByRole("button", { name: "Ask the agent" }));
  return user;
}

describe("RequestsPage", () => {
  beforeEach(() => localStorage.clear());

  it("shows the proposal with the line's why and the approvals link", async () => {
    await ask();

    const proposal = await screen.findByRole("region", { name: "Proposal" });
    expect(within(proposal).getByRole("heading", { level: 2 })).toHaveTextContent(
      'Proposal for "1,000 L lactose-free milk by Monday"',
    );
    expect(within(proposal).getAllByText(/the other 949 L, rounded up to full cases of 5/).length).toBeGreaterThan(0);
    expect(within(proposal).getByRole("heading", { name: "Other options" })).toBeInTheDocument();
    expect(within(proposal).getByRole("link", { name: /Approvals/ })).toHaveAttribute("href", "/approvals");
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
