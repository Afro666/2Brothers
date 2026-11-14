import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { mapModelTrace } from "@/api/model-trace";
import { ModelTracePanel } from "@/components/purchasing/model-trace-panel";
import { formatNumber } from "@/lib/format";
import { LanguageProvider } from "@/lib/i18n";

const BUYER = {
  made_by: "model", reader: "buyer", model: "nemotron-3.5-super-vl", thinking: false,
  calls: 4, failed: 0, prompt_tokens: 23110, completion_tokens: 910, reasoning_tokens: 0,
  seconds: 6.214, attempts: 1, truncated: false,
  steps: [
    { by: "model", attempt: 1, tool: "search_products", query: "lactose free milk", count: 12 },
    { by: "model", attempt: 1, tool: "get_offer", products: 3, count: 3 },
    { by: "model", attempt: 1, tool: "simulate_order", count: 3, code: "NEEDS_APPROVAL" },
    { by: "code", attempt: 1, tool: "search_products", count: 2 },
    { by: "model", attempt: 1, tool: "request_approval", code: "PENDING" },
  ],
};

afterEach(() => {
  localStorage.clear();
});

const show = (value: unknown) =>
  render(
    <LanguageProvider>
      <ModelTracePanel trace={mapModelTrace(value)} />
    </LanguageProvider>,
  );

describe("ModelTracePanel", () => {
  it("shows one folded line and the steps when unfolded, with the engine line last", async () => {
    show(BUYER);
    const summary = screen.getByText("4 model calls, 6.2 s, thinking off");
    expect(screen.getByText("What Nemotron did")).toBeVisible();
    // The model did the work: the NVIDIA mark sits next to the words.
    expect(screen.getByTestId("nemotron-mark")).toBeInTheDocument();
    const details = summary.closest("details")!;
    expect(details.open).toBe(false);
    await userEvent.click(summary);
    expect(details.open).toBe(true);
    const items = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(items).toEqual([
      "Model: Searched the catalog for “lactose free milk”: 12 products",
      "Model: Asked the engine for an offer on 3 products: 3 lines",
      "Model: Checked the offer against the guards: needs a person’s approval",
      "Code: Searched the catalog: 2 products",
      "Model: Sent the offer to you for approval",
    ]);
    expect(screen.getByText("Quantities and prices: the engine. Approval: you.")).toBeInTheDocument();
  });

  it("says when a search found its products by meaning after the words found nothing (#1384)", async () => {
    show({
      ...BUYER,
      steps: [{ by: "code", attempt: 1, tool: "search_products", query: "talon maito", count: 3, code: "MEANING_FALLBACK" }],
    });
    await userEvent.click(screen.getByText("4 model calls, 6.2 s, thinking off"));
    expect(screen.getByRole("listitem")).toHaveTextContent(
      "Code: Searched the catalog for “talon maito”: 3 products — found by meaning (Atlas Vector Search) after the word search found nothing",
    );
  });

  it("says the parser answered and shows no model steps", () => {
    show({ ...BUYER, made_by: "rule", reader: "parser", model: null, thinking: null, calls: 0, seconds: 0, attempts: 0, steps: [] });
    expect(screen.getByText("The gateway’s request parser answered. No model ran.")).toBeVisible();
    expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
    expect(screen.queryByText(/model calls?,/)).not.toBeInTheDocument();
    expect(screen.getByText("Quantities and prices: the engine. Approval: you.")).toBeVisible();
    // No model ran: no NVIDIA mark.
    expect(screen.queryByTestId("nemotron-mark")).not.toBeInTheDocument();
  });

  it("shows a seller rule pick as a rule, and a policy rejection by its code", async () => {
    show({
      ...BUYER, reader: "seller", made_by: "rule", model: null, thinking: null, calls: 0, seconds: 0,
      steps: [{ by: "code", attempt: 1, tool: "shortlist", count: 5 }, { by: "code", attempt: 1, tool: "pick", code: "PICKED" }],
    });
    expect(screen.getByText("Picked by rule. No model ran.")).toBeVisible();
    expect(screen.queryByTestId("nemotron-mark")).not.toBeInTheDocument();
  });

  it("names one call in the singular, thinking on, a restart and cut steps", async () => {
    show({
      ...BUYER, calls: 1, thinking: true, attempts: 2, truncated: true,
      steps: [{ by: "model", attempt: 2, tool: "get_offer", code: "NEED_MISMATCH" }],
    });
    await userEvent.click(screen.getByText("1 model call, 6.2 s, thinking on"));
    expect(screen.getByRole("listitem")).toHaveTextContent("Model: Asked the engine for an offer — refused by the policy (NEED_MISMATCH)");
    expect(screen.getByText("The first run stopped without a proposal and was started once more.")).toBeVisible();
    expect(screen.getByText("Later steps were cut.")).toBeVisible();
  });

  it("shows nothing without a trace", () => {
    const { container } = show(null);
    expect(container).toBeEmptyDOMElement();
    expect(mapModelTrace({ made_by: "person", reader: "buyer" })).toBeNull();
  });

  // The live milk card of 14 Nov (#1867): one pick call, then the explanation call.
  const PICK = {
    ...BUYER, calls: 1, seconds: 0.276,
    steps: [
      { by: "code", attempt: 1, tool: "search_products", query: "lactose free milk", count: 20 },
      { by: "model", attempt: 1, tool: "pick", products: 2, code: "PICKED" },
    ],
  };
  const WRITTEN = { text: "A checked text.", model: "nemotron-3.5-super-vl", durationMs: 757 };
  const showWith = (value: unknown, explanation: typeof WRITTEN | { text: string; model: string; durationMs: null } | null) =>
    render(
      <LanguageProvider>
        <ModelTracePanel trace={mapModelTrace(value)} explanation={explanation} />
      </LanguageProvider>,
    );

  it("counts the explanation call and lists it as its own step with its time (#1867)", async () => {
    showWith(PICK, WRITTEN);
    // 1 pick call + 1 explanation call; 0.276 s + 0.757 s.
    const summary = screen.getByText("2 model calls, 1 s, thinking off");
    expect(screen.queryByText(/^1 model call/)).not.toBeInTheDocument();
    await userEvent.click(summary);
    const items = screen.getAllByRole("listitem").map((item) => item.textContent);
    expect(items).toEqual([
      "Code: Searched the catalog for “lactose free milk”: 20 products",
      "Model: Picked one product from the shortlist",
      "Model: Wrote the explanation on this card from the checked decision record: 0.8 s",
    ]);
  });

  it("counts the explanation call without a time when the gateway sent none", async () => {
    showWith(PICK, { ...WRITTEN, durationMs: null });
    await userEvent.click(screen.getByText("2 model calls, 0.3 s, thinking off"));
    expect(screen.getAllByRole("listitem").at(-1)).toHaveTextContent(
      /^Model: Wrote the explanation on this card from the checked decision record$/,
    );
  });

  it("keeps the count of the run alone while there is no explanation", () => {
    showWith(PICK, null);
    expect(screen.getByText("1 model call, 0.3 s, thinking off")).toBeInTheDocument();
  });

  it("does not say no model ran on a rule-made proposal that has a model explanation", () => {
    showWith({ ...BUYER, made_by: "rule", reader: "parser", model: null, thinking: null, calls: 0, seconds: 0, attempts: 0, steps: [] }, WRITTEN);
    expect(screen.queryByText(/No model ran/)).not.toBeInTheDocument();
    expect(screen.getByText("The gateway’s request parser made the proposal: no model picked the products.")).toBeVisible();
    expect(screen.getByText("Nemotron 3.5 Super VL wrote the explanation on this card: 1 model call, 0.8 s.")).toBeVisible();
    expect(screen.getByTestId("nemotron-mark")).toBeInTheDocument();
  });

  it("speaks Finnish", () => {
    localStorage.setItem("purchasing-language", "fi");
    show(BUYER);
    expect(screen.getByText("Mitä Nemotron teki")).toBeInTheDocument();
    // The number format is the viewer's Appearance setting, not the language.
    expect(screen.getByText(`4 mallikutsua, ${formatNumber(6.2)} s, ajattelu pois`)).toBeInTheDocument();
    expect(screen.getByText("Määrät ja hinnat: moottori. Hyväksyntä: sinä.")).toBeInTheDocument();
  });
});
