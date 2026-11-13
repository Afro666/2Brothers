import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/lib/theme";
import { createAppRouter } from "@/router";

async function renderKit() {
  const router = createAppRouter(createMemoryHistory({ initialEntries: ["/kit"] }));
  render(
    <ThemeProvider>
      <TooltipProvider>
        <RouterProvider router={router} />
      </TooltipProvider>
    </ThemeProvider>,
  );
  await screen.findByRole("heading", { level: 1, name: "Component kit" });
}

describe("/kit", () => {
  it("renders a section for every purchasing component", async () => {
    await renderKit();
    for (const name of [
      "ChefRequestBox",
      "StatusBadge",
      "UrgencyBadge",
      "OrderLinesTable",
      "MovProgress",
      "OfferCompare",
      "ProductCard",
      "ApprovalCard",
      "AuditTimeline",
      "MandateSummary",
    ]) {
      expect(screen.getByRole("heading", { level: 2, name })).toBeInTheDocument();
    }
    expect(screen.getAllByRole("navigation", { name: "Main" }).length).toBeGreaterThan(0);
  });

  it("shows sentinel stock as unknown and never as a number", async () => {
    await renderKit();
    const orders = screen.getByRole("region", { name: "OrderLinesTable" });
    expect(within(orders).getAllByText("unknown").length).toBeGreaterThan(0);
    expect(document.body.textContent).not.toMatch(/999[\s,.]?999/);
    // The real stock of 462775 is shown as measured.
    expect(within(orders).getAllByText("51 ST").length).toBeGreaterThan(0);
  });

  it("flags a closing time that has already passed", async () => {
    await renderKit();
    const orders = screen.getByRole("region", { name: "OrderLinesTable" });
    const passed = within(orders).getAllByText(/Thu 12 Nov, 15:00 \(passed\)/);
    expect(passed.length).toBeGreaterThan(0);
    expect(passed[0]).toHaveAttribute("data-closed", "true");
    // Sunday's cut-off is still open: no flag.
    const open = within(orders).getAllByText("Sun 15 Nov, 17:00");
    expect(open[0]).not.toHaveAttribute("data-closed");
  });

  it("shows the free-delivery gap in euros", async () => {
    await renderKit();
    expect(screen.getByText("€118.93 to free delivery")).toBeInTheDocument();
    expect(screen.getByText("Free delivery reached")).toBeInTheDocument();
  });

  it("marks missing allergen data as unknown", async () => {
    await renderKit();
    const catalog = screen.getByRole("region", { name: "ProductCard" });
    expect(within(catalog).getByText("Allergen data missing: unknown")).toBeInTheDocument();
    expect(within(catalog).getAllByText("Contains").length).toBeGreaterThan(0);
  });

  it("keeps the unknown-stock example waiting for supplier confirmation", async () => {
    await renderKit();
    const approvals = screen.getByRole("region", { name: "ApprovalCard" });
    expect(within(approvals).getByText(/Waiting for supplier stock confirmation/)).toBeVisible();
    expect(within(approvals).getByRole("button", { name: /^Approve/ })).toBeDisabled();
    expect(within(approvals).getByRole("button", { name: "Reject" })).toBeEnabled();
  });

  it("lists the audit steps oldest first", async () => {
    await renderKit();
    const audit = screen.getByRole("region", { name: "AuditTimeline" });
    const kinds = within(audit)
      .getAllByRole("listitem")
      .map((li) => li.getAttribute("data-kind"));
    expect(kinds).toEqual(["request", "search", "offer", "simulate", "approval", "order", "mandate_check", "approval"]);
  });
});
