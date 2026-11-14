import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProvider } from "@/api";
import { createMockApi } from "@/api/mock";
import { mapModelTrace } from "@/api/model-trace";
import type { Api } from "@/api/types";
import { ApprovalCard } from "@/components/purchasing/approval-card";
import { ModelTraceLine } from "@/components/purchasing/model-trace-panel";
import { formatNumber } from "@/lib/format";
import { LanguageProvider } from "@/lib/i18n";
import { approval, orders } from "@/mocks/milk-case";

// The live milk card of 14 Nov (#1867).
const PICK = mapModelTrace({
  made_by: "model", reader: "buyer", model: "nemotron-3.5-super-vl", thinking: false,
  calls: 1, seconds: 0.276, attempts: 1, truncated: false,
  steps: [{ by: "model", attempt: 1, tool: "pick", products: 2, code: "PICKED" }],
});
const RULE = mapModelTrace({
  made_by: "rule", reader: "parser", model: null, thinking: null, calls: 0, seconds: 0, attempts: 0, steps: [],
});

const line = (trace: ReturnType<typeof mapModelTrace>) =>
  render(
    <LanguageProvider>
      <ModelTraceLine trace={trace} />
    </LanguageProvider>,
  );

describe("the visible model line on the approval card (#1867)", () => {
  beforeEach(() => {
    localStorage.clear();
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("names the model, its calls and its time from the trace", () => {
    line(PICK);
    expect(screen.getByText("Picked by Nemotron 3.5 Super VL · 1 call · 0.3 s")).toBeVisible();
    expect(screen.getByTestId("nemotron-mark")).toBeInTheDocument();
  });

  it("uses the plural for several calls", () => {
    line({ ...PICK!, calls: 4, seconds: 6.214 });
    expect(screen.getByText("Picked by Nemotron 3.5 Super VL · 4 calls · 6.2 s")).toBeVisible();
  });

  it("says the rules made a proposal no model made, with no NVIDIA mark", () => {
    line(RULE);
    expect(screen.getByText("Made by the gateway’s rules, no model call")).toBeVisible();
    expect(screen.queryByTestId("nemotron-mark")).not.toBeInTheDocument();
  });

  it("shows nothing without a trace, and no invented model name", () => {
    const { container } = line(null);
    expect(container).toBeEmptyDOMElement();
  });

  it("is on the compact card, before Inspect is pressed", () => {
    render(<ApprovalCard request={{ ...approval, modelTrace: PICK }} order={orders.needsApproval} />);
    expect(screen.getByRole("button", { name: "Inspect" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText("Picked by Nemotron 3.5 Super VL · 1 call · 0.3 s")).toBeVisible();
  });

  it("is absent on a card with no trace", () => {
    render(<ApprovalCard request={{ ...approval, modelTrace: null }} order={orders.needsApproval} />);
    expect(screen.queryByText(/^Picked by /)).not.toBeInTheDocument();
    expect(screen.queryByText(/^Made by /)).not.toBeInTheDocument();
  });

  it("the card's panel counts the explanation call the card shows", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const api: Api = createMockApi();
    api.getProposalExplanation = vi.fn(async () => ({
      text: "A checked text.", model: "nemotron-3.5-super-vl", durationMs: 757,
    }));
    render(
      <ApiProvider api={api}>
        <ApprovalCard request={{ ...approval, modelTrace: PICK }} order={orders.needsApproval} />
      </ApiProvider>,
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const written = screen.getByRole("region", { name: "Short explanation" });
    expect(written).toHaveTextContent("Written by Nemotron 3.5 Super VL from the checked decision record · 1 call · 0.8 s");
    await user.click(screen.getByRole("button", { name: "Inspect" }));
    const panel = screen.getByText("What Nemotron did").closest("details")!;
    expect(within(panel).getByText("2 model calls, 1 s, thinking off")).toBeInTheDocument();
    expect(within(panel).queryByText(/^1 model call/)).not.toBeInTheDocument();
  });

  it("speaks Finnish", () => {
    localStorage.setItem("purchasing-language", "fi");
    line(PICK);
    expect(screen.getByText(`Valinnut Nemotron 3.5 Super VL · 1 kutsu · ${formatNumber(0.3)} s`)).toBeVisible();
  });
});
