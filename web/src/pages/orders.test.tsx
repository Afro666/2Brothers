import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("orders pages", () => {
  beforeEach(() => localStorage.clear());

  it("links from the order list to its detail and shows lines and filtered history", async () => {
    const user = userEvent.setup();
    renderApp("/orders");

    await user.click(await screen.findByRole("link", { name: /ORD-1042/ }));
    expect(await screen.findByRole("heading", { level: 1, name: "Order ORD-1042" })).toBeInTheDocument();
    expect(screen.getAllByText("Arla 1 L lactose free fat free UHT milk drink").length).toBeGreaterThan(0);

    await user.click(screen.getByRole("tab", { name: "History" }));
    expect(await screen.findByText("ORD-1042 placed for Mon 16 Nov")).toBeInTheDocument();
    expect(screen.queryByText("Asked the buyer to approve ORD-1043")).not.toBeInTheDocument();
  });

  it("shows the API error for an unknown id", async () => {
    const api = createMockApi();
    const message = "Order ORD-missing was not found.";
    api.getOrder = async () => {
      throw new ApiError("NOT_FOUND", message);
    };
    renderApp("/orders/ORD-missing", api);

    expect(await screen.findByRole("alert")).toHaveTextContent(message);
    expect(screen.getByRole("heading", { level: 1, name: "Order ORD-missing" })).toBeInTheDocument();
  });
});
