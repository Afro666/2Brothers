import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiProvider } from "@/api";
import { createMockApi } from "@/api/mock";
import { LearnedBadge } from "@/components/purchasing/learned-badge";
import { LanguageProvider } from "@/lib/i18n";
import type { LearnedAdjustment } from "@/types";

vi.mock("@/lib/session", () => ({
  useSession: () => ({ session: { kind: "human", name: "Buyer", canApprove: true } }),
}));

let mockRole = "buyer";
vi.mock("@/lib/role", () => ({ useRole: () => ({ role: mockRole }) }));

const LEARNED: LearnedAdjustment = {
  factId: "lf_demo_potato_ratio",
  fromQty: "40",
  toQty: "20",
  unit: "KG",
  ratio: 0.5,
  evidence: { rows: 4, from: "2026-09-21", to: "2026-11-09", last: "2026-11-09" },
};

function renderBadge(onChanged?: () => void | Promise<void>, checkedSentence?: string) {
  const api = createMockApi();
  render(
    <LanguageProvider>
      <ApiProvider api={api}>
        <LearnedBadge learned={LEARNED} checkedSentence={checkedSentence} onChanged={onChanged} />
      </ApiProvider>
    </LanguageProvider>,
  );
  return api;
}

describe("LearnedBadge", () => {
  beforeEach(() => {
    localStorage.clear();
    mockRole = "buyer";
  });

  it("shows the badge, quantity change and plain evidence", async () => {
    const user = userEvent.setup();
    renderBadge();

    const badge = screen.getByRole("button", { name: "Learned from your changes" });
    expect(badge).toHaveClass("min-h-11");
    await user.click(badge);

    expect(await screen.findByText("40 kg → 20 kg")).toBeVisible();
    expect(screen.getByText(/4 changes, last on .*9 Nov/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Use the forecast instead" })).toHaveClass("min-h-11");
  });

  it("prefers Nemotron's checked sentence to the fallback evidence", async () => {
    const user = userEvent.setup();
    renderBadge(undefined, "Four kitchen corrections halved the potato forecast from 40 kg to 20 kg.");
    await user.click(screen.getByRole("button", { name: "Learned from your changes" }));

    expect(await screen.findByText("Four kitchen corrections halved the potato forecast from 40 kg to 20 kg.")).toBeVisible();
    expect(screen.queryByText(/4 changes, last on/)).not.toBeInTheDocument();
  });

  it("switches off the fact and refreshes the line", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn(async () => {});
    const api = renderBadge(onChanged);
    const update = vi.spyOn(api, "setLearnedFactActive");

    await user.click(screen.getByRole("button", { name: "Learned from your changes" }));
    await user.click(await screen.findByRole("button", { name: "Use the forecast instead" }));

    expect(update).toHaveBeenCalledWith("lf_demo_potato_ratio", false, "human");
    expect(onChanged).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Learned from your changes" })).not.toBeInTheDocument();
    expect((await api.listLearnedFacts()).find((fact) => fact.id === LEARNED.factId)?.active).toBe(false);
  });

  it("shows the evidence but no switch to the demo Chef role", async () => {
    const user = userEvent.setup();
    mockRole = "chef";
    renderBadge();

    await user.click(screen.getByRole("button", { name: "Learned from your changes" }));

    expect(await screen.findByText("40 kg → 20 kg")).toBeVisible();
    expect(screen.getByText("Only an approver can switch off learned facts.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Use the forecast instead" })).not.toBeInTheDocument();
  });

  it("keeps the badge and says so when the switch fails", async () => {
    const user = userEvent.setup();
    const onChanged = vi.fn();
    const api = renderBadge(onChanged);
    vi.spyOn(api, "setLearnedFactActive").mockRejectedValue(new Error("The gateway is unavailable."));

    await user.click(screen.getByRole("button", { name: "Learned from your changes" }));
    await user.click(await screen.findByRole("button", { name: "Use the forecast instead" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not use the forecast instead: The gateway is unavailable.");
    expect(onChanged).not.toHaveBeenCalled();
    expect(screen.getByRole("button", { name: "Use the forecast instead" })).toBeEnabled();
  });
});
