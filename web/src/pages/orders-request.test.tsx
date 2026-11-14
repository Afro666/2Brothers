import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { formatDateTime } from "@/lib/format";
import { renderApp } from "@/test/render";

// Aron, 14 Nov: repeated demo orders of one product must not look like duplicates.
describe("order history: what was asked, and when", () => {
  beforeEach(() => localStorage.clear());

  it("shows each order's request text and its date and time", async () => {
    const api = createMockApi();
    const [order] = await api.listOrders();
    api.listOrders = async () => [
      { ...order, id: "ORD-A", requestText: "1,000 L lactose-free milk by Monday", createdAt: "2026-11-14T08:15:00Z" },
      { ...order, id: "ORD-B", requestText: "Milk for the school lunches", createdAt: "2026-11-14T11:40:00Z" },
    ];
    renderApp("/orders", api);

    const first = (await screen.findByText("Asked: “1,000 L lactose-free milk by Monday”")).closest("li")!;
    expect(within(first).getByText(`Ordered ${formatDateTime("2026-11-14T08:15:00Z")}`)).toBeVisible();
    const second = screen.getByText("Asked: “Milk for the school lunches”").closest("li")!;
    expect(within(second).getByText(`Ordered ${formatDateTime("2026-11-14T11:40:00Z")}`)).toBeVisible();
    expect(first).not.toBe(second);
  });

  it("shows neither line when the order has no request text or time", async () => {
    const api = createMockApi();
    const [first] = await api.listOrders();
    api.listOrders = async () => [{ ...first, requestText: null, createdAt: null }];
    renderApp("/orders", api);

    await screen.findByText(/incl VAT/);
    expect(screen.queryByText(/^Asked:/)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Ordered /)).not.toBeInTheDocument();
  });
});
