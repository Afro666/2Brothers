import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import type { Api } from "@/api/types";
import { renderApp } from "@/test/render";

function rowFor(productName: string): HTMLElement {
  const rows = screen.getAllByText(productName).map((node) => node.closest("tr") ?? node.closest("li"));
  const row = rows[0];
  if (!row) throw new Error(`No row for ${productName}`);
  return row;
}

describe("StockPage", () => {
  beforeEach(() => localStorage.clear());

  it("shows an uncounted product as not counted, never as zero", async () => {
    renderApp("/stock", createMockApi());

    await screen.findByText(/not counted: treated as unknown, not as zero/);
    expect(screen.getByText("4 of 8 not counted: treated as unknown, not as zero")).toBeInTheDocument();
    expect(rowFor("Valio Eila 3 % milk")).toHaveTextContent("not counted");
    expect(rowFor("Valio Eila novobox milk")).toHaveTextContent("0 L");
  });

  it("saves a typed count, reloads the row and records a stock audit event", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/stock", api);

    await screen.findByText(/not counted: treated as unknown, not as zero/);
    await user.type(screen.getAllByRole("textbox", { name: "Valio Eila 3 % milk count in L" })[0], "42");
    await user.click(screen.getByRole("button", { name: "Save count" }));

    expect(await screen.findByTestId("stock-count-saved-toast")).toHaveTextContent("Count saved");
    expect(screen.getAllByText("Count saved")).toHaveLength(1);
    await waitFor(() => expect(rowFor("Valio Eila 3 % milk")).toHaveTextContent("42 L"));
    expect(screen.getByText("3 of 8 not counted: treated as unknown, not as zero")).toBeInTheDocument();
    const events = (await api.listAudit()).filter((event) => event.kind === "stock");
    expect(events.at(-1)).toMatchObject({ actor: "human", summary: "Stock count submitted for 1 products" });
  });

  it("keeps an unknown count when the row is marked Not counted", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/stock", api);

    await screen.findByText(/not counted: treated as unknown, not as zero/);
    const row = rowFor("Arla lactose-free milk");
    expect(row).toHaveTextContent("18 L");
    await user.click(screen.getAllByRole("checkbox", { name: "Arla lactose-free milk not counted" })[0]);
    await user.click(screen.getByRole("button", { name: "Save count" }));

    expect(await screen.findByTestId("stock-count-saved-toast")).toHaveTextContent("Count saved");
    await waitFor(() => expect(rowFor("Arla lactose-free milk")).toHaveTextContent("not counted"));
    const stock = await api.getStock();
    expect(stock.find((item) => item.productId === "462775")).toMatchObject({ onHand: null });
  });

  it("shows a failed save inline and keeps what the user typed", async () => {
    const user = userEvent.setup();
    const api: Api = createMockApi();
    api.submitStockCount = async () => {
      throw new Error("The count did not reach the gateway.");
    };
    renderApp("/stock", api);

    await screen.findByText(/not counted: treated as unknown, not as zero/);
    await user.type(screen.getAllByRole("textbox", { name: "Salmon fillet count in KG" })[0], "7");
    await user.click(screen.getByRole("button", { name: "Save count" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("The count did not reach the gateway.");
    expect(screen.getAllByRole("textbox", { name: "Salmon fillet count in KG" })[0]).toHaveValue("7");
    expect(screen.queryByRole("status", { name: "" })).not.toBeInTheDocument();
  });

  it("refuses to save a touched row with a negative or non-numeric count", async () => {
    const user = userEvent.setup();
    const api: Api = createMockApi();
    const submit = api.submitStockCount;
    let submitted: unknown = null;
    api.submitStockCount = async (counts, actor) => {
      submitted = counts;
      return submit(counts, actor);
    };
    renderApp("/stock", api);

    await screen.findByText(/not counted: treated as unknown, not as zero/);
    await user.type(screen.getAllByRole("textbox", { name: "Salmon fillet count in KG" })[0], "7");
    const milk = screen.getAllByRole("textbox", { name: "Valio Eila 3 % milk count in L" })[0];
    await user.clear(milk);
    expect(milk).toHaveAttribute("aria-invalid", "false");
    await user.type(milk, "-4");

    expect(await within(rowFor("Valio Eila 3 % milk")).findByRole("alert")).toHaveTextContent(
      "A count cannot be negative.",
    );
    expect(milk).toHaveAttribute("aria-invalid", "true");
    expect(screen.getByRole("button", { name: "Save count" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Save count" }));
    expect(submitted).toBeNull();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    await user.clear(milk);
    await user.type(milk, "1e");
    expect(await within(rowFor("Valio Eila 3 % milk")).findByRole("alert")).toHaveTextContent("Enter a number.");
    expect(screen.getByRole("button", { name: "Save count" })).toBeDisabled();
    expect(milk).toHaveValue("1e");

    // A corrected row lets the valid salmon count go through.
    await user.clear(milk);
    await user.type(milk, "12");
    expect(screen.getByRole("button", { name: "Save count" })).toBeEnabled();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: "Save count" }));
    expect(await screen.findByTestId("stock-count-saved-toast")).toHaveTextContent("Count saved");
    expect(submitted).toEqual([
      { productId: "463335", onHand: 12 },
      { productId: "OWN-SALMON", onHand: 7 },
    ]);
  });

  it("treats a cleared count or an unticked Not counted as untouched, so Save works for the rest", async () => {
    const user = userEvent.setup();
    const api: Api = createMockApi();
    const submit = api.submitStockCount;
    let submitted: unknown = null;
    api.submitStockCount = async (counts, actor) => {
      submitted = counts;
      return submit(counts, actor);
    };
    renderApp("/stock", api);

    await screen.findByText(/not counted: treated as unknown, not as zero/);
    await user.type(screen.getAllByRole("textbox", { name: "Salmon fillet count in KG" })[0], "7");
    const milk = screen.getAllByRole("textbox", { name: "Valio Eila 3 % milk count in L" })[0];
    await user.type(milk, "5");
    await user.clear(milk);
    const arla = screen.getAllByRole("checkbox", { name: "Arla lactose-free milk not counted" })[0];
    await user.click(arla);
    await user.click(arla);

    expect(within(rowFor("Valio Eila 3 % milk")).queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryAllByRole("alert")).toHaveLength(0);
    expect(milk).toHaveAttribute("aria-invalid", "false");
    expect(screen.getByRole("button", { name: "Save count" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Save count" }));
    expect(await screen.findByTestId("stock-count-saved-toast")).toHaveTextContent("Count saved");
    expect(submitted).toEqual([{ productId: "OWN-SALMON", onHand: 7 }]);
  });

  it("locks the inputs and the Save button while the count is in flight", async () => {
    const user = userEvent.setup();
    const api: Api = createMockApi();
    let release: () => void = () => undefined;
    const inFlight = new Promise<void>((resolve) => {
      release = resolve;
    });
    const save = api.submitStockCount;
    const submitted: unknown[] = [];
    api.submitStockCount = async (counts) => {
      submitted.push(counts);
      await inFlight;
      return save(counts, "human");
    };
    renderApp("/stock", api);

    await screen.findByText(/not counted: treated as unknown, not as zero/);
    const counts = screen.getAllByRole("textbox", { name: /count in/ });
    const checkboxes = screen.getAllByRole("checkbox", { name: /not counted$/ });
    await user.type(screen.getAllByRole("textbox", { name: "Salmon fillet count in KG" })[0], "7");
    await user.click(screen.getByRole("button", { name: "Save count" }));

    const busy = await screen.findByRole("button", { name: "Saving count" });
    expect(busy).toBeDisabled();
    expect(busy).toHaveAttribute("aria-busy", "true");
    for (const input of counts) expect(input).toBeDisabled();
    for (const checkbox of checkboxes) expect(checkbox).toBeDisabled();
    expect(screen.getAllByRole("textbox", { name: "Salmon fillet count in KG" })[0]).toHaveValue("7");

    release();
    expect(await screen.findByTestId("stock-count-saved-toast")).toHaveTextContent("Count saved");
    expect(submitted).toHaveLength(1);
    await waitFor(() => expect(screen.getAllByRole("textbox", { name: /count in/ })[0]).toBeEnabled());
  });

  it("explains the page, not just the title", async () => {
    renderApp("/stock", createMockApi());
    expect(
      await screen.findByText("What is on hand and on order. A product nobody counted is unknown, not zero."),
    ).toBeInTheDocument();
  });
});
