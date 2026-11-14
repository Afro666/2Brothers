import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApprovalCard } from "@/components/purchasing/approval-card";
import { ProposalLines } from "@/components/purchasing/proposal-lines";
import { formatDateTime, formatEur } from "@/lib/format";
import { LanguageProvider } from "@/lib/i18n";
import { splitChecks, statusChips } from "@/lib/proposal-checks";
import { MOCK_NOW } from "@/mocks/milk-case";
import { menuPlanApproval, menuPlanLines, menuPlanOrder } from "@/mocks/menu-plan-case";

const byId = (id: string) => menuPlanLines.find((line) => line.product.id === id)!;

function rowOf(name: string) {
  return screen.getByText(name, { selector: "div" }).closest('[role="row"]') as HTMLElement;
}

/** The Delivery column's cell (the sixth; the Stock cell repeats it for phones). */
function deliveryCell(row: HTMLElement) {
  return within(row).getAllByRole("cell")[5];
}

describe("ProposalLines: the lines of a proposal as a table", () => {
  it("has one column per fact, one row per product, names with brand and code", () => {
    render(<ProposalLines lines={menuPlanLines} now={MOCK_NOW} confirmBy="Valio" checks={new Map()} />);
    const table = screen.getByRole("table", { name: "Order lines" });
    expect(within(table).getAllByRole("columnheader").map((cell) => cell.textContent)).toEqual([
      "Product",
      "Qty",
      "Price",
      "Total",
      "Stock",
      "Delivery",
      "Why this much",
    ]);
    expect(screen.getByText("All prices ex VAT")).toBeVisible();
    expect(screen.getAllByTestId("proposal-line")).toHaveLength(menuPlanLines.length);
    const cream = byId("404233");
    const row = rowOf(cream.product.names.en);
    expect(row).toHaveTextContent("Valio · 404233");
    expect(row).toHaveTextContent(`36 pieces`);
    expect(row).toHaveTextContent(formatEur(cream.offer.priceExVat));
    expect(row).toHaveTextContent(formatEur(cream.lineTotal));
    expect(row).toHaveTextContent(cream.why);
    // Not editable: no inputs, no remove buttons.
    expect(screen.queryByRole("spinbutton")).toBeNull();
    expect(screen.queryByRole("button", { name: /^Remove / })).toBeNull();
  });

  it("shows stock as a chip: confirmed amount, who must confirm, or not available", () => {
    render(<ProposalLines lines={menuPlanLines} now={MOCK_NOW} confirmBy="Valio" checks={new Map()} />);
    expect(within(rowOf(byId("404151").product.names.en)).getByText("2,400 pieces")).toHaveAttribute("data-stock", "success");
    expect(within(rowOf(byId("404233").product.names.en)).getByText("Valio must confirm")).toHaveAttribute("data-stock", "warning");
    expect(within(rowOf(byId("405322").product.names.en)).getByText("Not available")).toHaveAttribute("data-stock", "danger");
  });

  it("says a passed cut-off on its row, and the order-by time otherwise", () => {
    render(<ProposalLines lines={menuPlanLines} now={MOCK_NOW} confirmBy="Valio" checks={new Map()} />);
    expect(within(rowOf(byId("404933").product.names.en)).getAllByText("Cut-off passed").length).toBeGreaterThan(0);
    expect(within(rowOf(byId("404151").product.names.en)).queryByText("Cut-off passed")).toBeNull();
    const milk = byId("404151");
    expect(within(rowOf(milk.product.names.en)).getAllByText(formatDateTime(milk.offer.closingTime)).length).toBeGreaterThan(0);
  });

  it("shows lead time in days and reliability as a percentage, with (demo) only on demo values (#1453)", () => {
    const [milk, cream, cheese] = [byId("404151"), byId("404233"), byId("404318")];
    const lines = [
      { ...milk, offer: { ...milk.offer, cutoffSource: "demo" as const, leadTimeDays: 2, leadTimeSource: "demo" as const, deliveryReliability: 0.97, reliabilitySource: "valio" as const } },
      { ...cream, offer: { ...cream.offer, cutoffSource: "valio" as const, leadTimeDays: 1, leadTimeSource: "supplier_terms" as const, deliveryReliability: 0.9, reliabilitySource: "demo" as const } },
      // A proposal stored before #1453: no delivery facts at all.
      { ...cheese, offer: { ...cheese.offer, cutoffSource: null, leadTimeDays: null, leadTimeSource: null, deliveryReliability: null, reliabilitySource: null } },
    ];
    render(<ProposalLines lines={lines} now={MOCK_NOW} confirmBy="Valio" checks={new Map()} />);
    const milkRow = rowOf(milk.product.names.en);
    expect(within(milkRow).getAllByText(/2 days/).length).toBeGreaterThan(0);
    expect(within(milkRow).getAllByText(/97 % delivered/).length).toBeGreaterThan(0);
    // The cut-off and the lead time are demo values; the reliability is Valio's. Two demo
    // values in one Delivery cell still give one "(demo)", which names both.
    const milkCell = deliveryCell(milkRow);
    const milkDemo = milkCell.querySelectorAll("[data-demo]");
    expect(milkDemo).toHaveLength(1);
    expect(milkCell.textContent?.match(/\(demo\)/g)).toHaveLength(1);
    expect(milkDemo[0]).toHaveAttribute("title", "Demo data: Order cut-off, Lead time");
    // At the end of the cell, after the last value.
    expect(milkDemo[0].previousElementSibling).toHaveAttribute("title", "Delivery reliability");
    const creamRow = rowOf(cream.product.names.en);
    expect(within(creamRow).getAllByText(/^1 day/).length).toBeGreaterThan(0);
    const creamDemo = deliveryCell(creamRow).querySelectorAll("[data-demo]");
    expect(creamDemo).toHaveLength(1);
    expect(creamDemo[0]).toHaveAttribute("title", "Demo data: Delivery reliability");
    // No facts, no note and no invented figure.
    const cheeseRow = rowOf(byId("404318").product.names.en);
    expect(cheeseRow.querySelector("[data-demo]")).toBeNull();
    expect(within(cheeseRow).queryByText(/delivered/)).toBeNull();
  });

  it("folds a long why to two lines and opens it by keyboard", async () => {
    const user = userEvent.setup();
    render(<ProposalLines lines={menuPlanLines} now={MOCK_NOW} confirmBy="Valio" checks={new Map()} />);
    const milk = byId("404151");
    const toggle = screen.getByRole("button", { name: `Show all of why for ${milk.product.names.en}` });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(milk.why)).toHaveAttribute("title", milk.why);
    toggle.focus();
    await user.keyboard("{Enter}");
    expect(screen.getByRole("button", { name: `Show less of why for ${milk.product.names.en}` })).toHaveAttribute("aria-expanded", "true");
  });

  it("edits a quantity inline: Enter or the check button updates, the icon button removes", async () => {
    const user = userEvent.setup();
    const onUpdate = vi.fn();
    const onRemove = vi.fn();
    let typed = "";
    const line = byId("404318");
    const { rerender } = render(
      <ProposalLines
        lines={[line]}
        now={MOCK_NOW}
        confirmBy="Valio"
        checks={new Map()}
        editing={{ busy: false, value: () => typed || String(line.quantity), onType: (_l, v) => (typed = v), onUpdate, onRemove, inputId: () => "qty-x" }}
      />,
    );
    const update = screen.getByRole("button", { name: `Update ${line.product.names.en}` });
    expect(update).toBeDisabled();
    typed = "20";
    rerender(
      <ProposalLines
        lines={[line]}
        now={MOCK_NOW}
        confirmBy="Valio"
        checks={new Map()}
        editing={{ busy: false, value: () => typed, onType: (_l, v) => (typed = v), onUpdate, onRemove, inputId: () => "qty-x" }}
      />,
    );
    const input = screen.getByRole("spinbutton", { name: `Quantity for ${line.product.names.en} (kg)` });
    expect(input).toHaveValue(20);
    await user.type(input, "{Enter}");
    expect(onUpdate).toHaveBeenCalledTimes(1);
    await user.click(screen.getByRole("button", { name: `Update ${line.product.names.en}` }));
    expect(onUpdate).toHaveBeenCalledTimes(2);
    await user.click(screen.getByRole("button", { name: `Remove ${line.product.names.en}` }));
    expect(onRemove).toHaveBeenCalledWith(line);
  });
});

describe("splitChecks: What to check, per product", () => {
  it("puts a product's reasons on its row, lists left-out products, and keeps the rest proposal-wide", () => {
    const { perLine, leftOut, general } = splitChecks(
      [
        ...menuPlanApproval.reasons,
        { rule: `${byId("404151").product.names.en}: Allergen rule: the kitchen excludes AN`, detail: "" },
        { rule: "Valio Eila milk 1 L (405418): label checked", detail: "" },
      ],
      menuPlanLines,
    );
    expect(perLine.get("404933")).toEqual([{ text: "order cut-off has passed", detail: "" }]);
    expect(perLine.get("405322")).toEqual([{ text: "not available for this date", detail: "" }]);
    expect(perLine.get("404151")).toEqual([{ text: "Allergen rule: the kitchen excludes AN", detail: "" }]);
    expect(perLine.get("405418")).toEqual([{ text: "label checked", detail: "" }]);
    expect(leftOut).toEqual([
      { product: "463132", reason: "order cut-off has passed", detail: "" },
      { product: "463335", reason: "order cut-off has passed", detail: "" },
    ]);
    expect(general.map((reason) => reason.rule)).toEqual([
      "The total is above your kitchen's budget warning.",
      expect.stringMatching(/^Valio must confirm stock for: /),
    ]);
  });

  it("in Finnish translates a per-product reason's detail on its row and in the left-out list", () => {
    const detail = "A warning only. It does not block the order.";
    const finnish = "Tämä on vain varoitus. Se ei estä tilausta.";
    const { perLine, leftOut } = splitChecks(
      [
        { rule: "404933: order cut-off has passed", detail },
        { rule: "463132: order cut-off has passed", detail },
      ],
      menuPlanLines,
    );
    localStorage.setItem("purchasing-language", "fi");
    try {
      render(
        <LanguageProvider>
          <ProposalLines lines={menuPlanLines} now={MOCK_NOW} confirmBy="Valio" checks={perLine} leftOut={leftOut} />
        </LanguageProvider>,
      );
      const hasFinnish = (content: string, element: Element | null) =>
        element?.tagName === "SPAN" && content.includes(finnish);
      const row = rowOf(byId("404933").product.names.en);
      expect(within(row).getByText(hasFinnish)).toBeInTheDocument();
      const list = screen.getByRole("region");
      expect(within(list).getByText(hasFinnish)).toBeInTheDocument();
      expect(screen.queryByText((content) => content.includes(detail))).not.toBeInTheDocument();
    } finally {
      localStorage.removeItem("purchasing-language");
      // The provider keeps the language in memory; mounting it again reads English back.
      render(<LanguageProvider>{null}</LanguageProvider>);
    }
  });

  it("names the status chips most serious first", () => {
    const { leftOut } = splitChecks(menuPlanApproval.reasons, menuPlanLines);
    const chips = statusChips({ request: menuPlanApproval, order: menuPlanOrder, now: MOCK_NOW, heldByRecall: false, leftOut: leftOut.length });
    expect(chips.map((chip) => [chip.text, chip.values?.count])).toEqual([
      ["Not available {count}", 1],
      ["Cut-off passed {count}", 1],
      ["Over budget", undefined],
      ["Valio must confirm {count}", 3],
      ["Left out: {count}", 2],
    ]);
  });
});

describe("ApprovalCard: a menu plan of many lines", () => {
  it("is compact until Inspect: chips, total and decision first; the table and checks behind one toggle", async () => {
    const user = userEvent.setup();
    render(<ApprovalCard request={menuPlanApproval} order={menuPlanOrder} now={MOCK_NOW} onApprove={vi.fn()} onReject={vi.fn()} />);
    expect(screen.getByText(menuPlanApproval.summary)).toBeVisible();
    expect(screen.getByText(formatEur(menuPlanApproval.totalInclVat))).toBeVisible();
    // At most three chips, the most serious first.
    const chips = within(screen.getByRole("list", { name: "Status" })).getAllByRole("listitem");
    expect(chips.map((chip) => chip.textContent)).toEqual(["Not available 1", "Cut-off passed 1", "Over budget"]);
    expect(screen.queryByTestId("proposal-lines")).toBeNull();
    expect(screen.queryByText("What to check")).toBeNull();
    expect(screen.getByRole("button", { name: /^Approve / })).toBeEnabled();

    const inspect = screen.getByRole("button", { name: "Inspect" });
    expect(inspect).toHaveAttribute("aria-expanded", "false");
    const panel = document.getElementById(inspect.getAttribute("aria-controls")!)!;
    expect(panel).not.toBeVisible();
    inspect.focus();
    await user.keyboard("{Enter}");
    expect(inspect).toHaveAttribute("aria-expanded", "true");
    expect(panel).toBeVisible();
    expect(within(panel).getAllByTestId("proposal-line")).toHaveLength(menuPlanLines.length);
    // The per-product check is on its row, not a separate bar per product id.
    expect(within(rowOf(byId("404933").product.names.en)).getByText("order cut-off has passed")).toBeVisible();
    expect(within(panel).getByText("Left out of this order (2)")).toBeVisible();
    const checks = within(panel).getByRole("heading", { name: "What to check" }).closest("section")!;
    expect(within(checks).queryByText(/^404933/)).toBeNull();
    expect(within(checks).getByText("The total is above your kitchen's budget warning.")).toBeVisible();
    await user.keyboard(" ");
    expect(inspect).toHaveAttribute("aria-expanded", "false");
  });

  it("opens Add products only on its button, closed by default", async () => {
    const user = userEvent.setup();
    const listAddableProducts = vi.fn().mockResolvedValue([]);
    render(
      <ApprovalCard
        request={menuPlanApproval}
        order={menuPlanOrder}
        now={MOCK_NOW}
        onChangeProposal={vi.fn()}
        listAddableProducts={listAddableProducts}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    const add = screen.getByRole("button", { name: "Add products" });
    expect(add).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("searchbox", { name: "Search products" })).toBeNull();
    expect(listAddableProducts).not.toHaveBeenCalled();
    await user.click(add);
    expect(add).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByRole("searchbox", { name: "Search products" })).toBeVisible();
    expect(await screen.findByText("No products found.")).toBeVisible();
    expect(listAddableProducts).toHaveBeenCalledWith("");
    // Every line is editable inline in the table.
    expect(screen.getAllByRole("spinbutton", { name: /^Quantity for / })).toHaveLength(menuPlanLines.length);
    expect(screen.getAllByRole("button", { name: /^Remove / })).toHaveLength(menuPlanLines.length);
  });
});
