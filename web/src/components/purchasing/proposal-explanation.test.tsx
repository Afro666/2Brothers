import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApiProvider } from "@/api";
import type { Api, ProposalExplanation } from "@/api/types";
import { ApprovalCard } from "@/components/purchasing/approval-card";
import { EXPLANATION_POLL_LIMIT, EXPLANATION_POLL_MS } from "@/lib/proposal-explanation";
import { approval, orders } from "@/mocks/milk-case";

const confirmedOrder = {
  ...orders.needsApproval,
  lines: orders.needsApproval.lines.map((line) => ({
    ...line,
    offer: { ...line.offer, availableAmount: line.quantity },
  })),
};

const text: ProposalExplanation = {
  text: "You chose 950 L of Valio Eila 3 % milk. The total is over the €1,500 warning level.",
  model: "nemotron-3.5-super-vl",
  durationMs: 1540,
};

function apiWith(answers: (ProposalExplanation | null)[]): Api {
  const api = createMockApi();
  const list = [...answers];
  api.getProposalExplanation = vi.fn(async () => list.shift() ?? null);
  return api;
}

// Every card starts compact (Aron, 2026-11-14): the decision record opens on Inspect.
function renderCard(api: Api, request = approval) {
  return render(
    <ApiProvider api={api}>
      <ApprovalCard request={request} order={confirmedOrder} />
    </ApiProvider>,
  );
}

function explanationText() {
  return document.querySelector("[data-proposal-explanation]")?.textContent ?? null;
}

describe("the explanation at the top of the approval card (#1173)", () => {
  beforeEach(() => {
    localStorage.clear();
    vi.useFakeTimers({ shouldAdvanceTime: true });
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("renders exactly as before while there is no explanation", async () => {
    const api = apiWith([null]);
    const { container } = renderCard(api);
    // The compact card shows product pictures at once; let their brand logos arrive first,
    // so only the explanation can change the card after this point.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const before = container.innerHTML;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(5 * 60_000);   // long after the backoff ends (#1399)
    });
    expect(explanationText()).toBeNull();
    expect(screen.queryByText("Short explanation")).toBeNull();
    expect(container.innerHTML).toBe(before);
    // The empty answers changed nothing, and asking stopped.
    expect(api.getProposalExplanation).toHaveBeenCalledTimes(EXPLANATION_POLL_LIMIT);
    expect((api.getProposalExplanation as ReturnType<typeof vi.fn>).mock.calls[0]).toEqual([approval.id, "en"]);
  });

  it("shows the text that arrives on the second poll above the totals", async () => {
    const api = apiWith([null, text]);
    renderCard(api);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(explanationText()).toBeNull();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXPLANATION_POLL_MS);
    });
    const shown = screen.getByRole("region", { name: "Short explanation" });
    expect(shown).toHaveTextContent(text.text);
    expect(shown).toHaveTextContent("Written by Nemotron 3.5 Super VL from the checked decision record");
    // Nemotron wrote it: the NVIDIA mark sits next to "Written by".
    expect(within(shown).getByTestId("nemotron-mark")).toBeInTheDocument();
    // Above the totals, below the title.
    const totals = screen.getByText("Total ex VAT").closest("dl")!;
    expect(shown.compareDocumentPosition(totals) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    const title = screen.getByText(approval.summary);
    expect(title.compareDocumentPosition(shown) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("renders model text as text, never as HTML", async () => {
    const api = apiWith([{ ...text, text: "<b>Not bold</b>" }]);
    renderCard(api);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(explanationText()).toBe("<b>Not bold</b>");
    expect(explanationText()?.includes("<b>")).toBe(true);
    expect(document.querySelector("[data-proposal-explanation] b")).toBeNull();
  });

  it("names the model the gateway sent", async () => {
    const api = apiWith([{ ...text, model: "nemotron-4.2-super-vl" }]);
    renderCard(api);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.getByText(/^Written by /)).toHaveTextContent("Nemotron 4.2 Super VL");
  });

  it("shows no NVIDIA mark when another model wrote the explanation", async () => {
    const api = apiWith([{ ...text, model: "other-model-1" }]);
    renderCard(api);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const shown = screen.getByRole("region", { name: "Short explanation" });
    expect(shown).toHaveTextContent("Written by other-model-1");
    expect(within(shown).queryByTestId("nemotron-mark")).toBeNull();
  });

  it("opens the full decision record from a compact card without duplicating it", async () => {
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    const api = apiWith([text]);
    renderCard(api, approval);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.queryByText("What to check")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open the full decision record" }));
    expect(screen.getByRole("heading", { name: "What to check" })).toBeVisible();
    expect(screen.getAllByText(/Over the budget warning/)).toHaveLength(1);
  });

  it("does not ask for a decided proposal", async () => {
    const api = apiWith([text]);
    renderCard(api, { ...approval, status: "REJECTED" });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(EXPLANATION_POLL_MS * 6);
    });
    expect(api.getProposalExplanation).not.toHaveBeenCalled();
    expect(explanationText()).toBeNull();
  });
});
