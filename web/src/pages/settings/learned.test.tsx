import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("What the tool learned settings", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => vi.unstubAllGlobals());

  it("lists each fact, its evidence, start date and active state", async () => {
    renderApp("/settings/learned");

    expect(await screen.findByText("Washed potato 10 kg")).toBeVisible();
    expect(screen.getByRole("heading", { name: "What the tool learned" })).toBeVisible();
    expect(screen.getByText("Quantity correction: 0.5 × the forecast")).toBeVisible();
    expect(screen.getAllByText(/4 recorded events from/)).toHaveLength(1);
    expect(screen.getByRole("switch", { name: "Use learned fact for Washed potato 10 kg" })).toBeChecked();
    expect(screen.getByRole("switch", { name: "Use learned fact for Leipomo Demo" })).not.toBeChecked();
    expect(screen.getByText("Supplier delivery timing: 1 day late on average")).toBeVisible();
  });

  it("uses the plural for a supplier that is late by more than a day", async () => {
    const api = createMockApi();
    const facts = await api.listLearnedFacts();
    vi.spyOn(api, "listLearnedFacts").mockResolvedValue(
      facts.map((fact) => (fact.kind === "SUPPLIER_LATE" ? { ...fact, value: 2.5, meanDaysLate: 2.5 } : fact)),
    );
    renderApp("/settings/learned", api);

    expect(await screen.findByText("Supplier delivery timing: 2.5 days late on average")).toBeVisible();
  });

  it("lets an approver switch off a fact", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const update = vi.spyOn(api, "setLearnedFactActive");
    renderApp("/settings/learned", api);

    const control = await screen.findByRole("switch", { name: "Use learned fact for Washed potato 10 kg" });
    await user.click(control);

    await waitFor(() => expect(control).not.toBeChecked());
    expect(control).toBeDisabled();
    expect(update).toHaveBeenCalledWith("lf_demo_potato_ratio", false, "human");
    expect((await api.listLearnedFacts()).find((fact) => fact.id === "lf_demo_potato_ratio")?.active).toBe(false);
  });

  it("shows a failure and leaves the switch as it was", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    vi.spyOn(api, "setLearnedFactActive").mockRejectedValue(new Error("The gateway is unavailable."));
    renderApp("/settings/learned", api);

    const control = await screen.findByRole("switch", { name: "Use learned fact for Washed potato 10 kg" });
    await user.click(control);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not switch off this learned fact: The gateway is unavailable.");
    expect(control).toBeChecked();
    expect(control).toBeEnabled();
  });

  it("shows the empty state", async () => {
    const api = createMockApi();
    vi.spyOn(api, "listLearnedFacts").mockResolvedValue([]);
    renderApp("/settings/learned", api);

    expect(await screen.findByText("Nothing learned yet: the tool learns from the reasons you give when you change an order.")).toBeVisible();
  });

  it("is read-only for a chef", async () => {
    const api = createMockApi();
    const update = vi.spyOn(api, "setLearnedFactActive");
    vi.spyOn(api, "getSession").mockResolvedValue({
      name: "Chef",
      email: "chef@demo.kitchen",
      role: "chef",
      canApprove: false,
      kind: "human",
    });
    renderApp("/settings/learned", api);

    const control = await screen.findByRole("switch", { name: "Use learned fact for Washed potato 10 kg" });
    expect(control).toBeDisabled();
    expect(screen.getByText("Read only: only an approver can switch off learned facts.")).toBeVisible();
    expect(screen.getByText("Washed potato 10 kg")).toBeVisible();
    expect(update).not.toHaveBeenCalled();
  });

  it("is read-only for the chef demo role and marks fallback facts as sample data", async () => {
    localStorage.setItem("purchasing-role", "chef");
    const api = Object.assign(createMockApi(), { live: new Set() });
    renderApp("/settings/learned", api);

    const control = await screen.findByRole("switch", { name: "Use learned fact for Washed potato 10 kg" });
    expect(control).toBeDisabled();
    expect(screen.getByText("Sample data")).toBeVisible();
  });

  it("says a ratio outside the trusted range is not applied", async () => {
    const api = createMockApi();
    const [potato, ...rest] = await api.listLearnedFacts();
    vi.spyOn(api, "listLearnedFacts").mockResolvedValue([{ ...potato, value: 1.5, rawValue: 2.4, applicable: false }, ...rest]);
    renderApp("/settings/learned", api);

    expect(await screen.findByText("Not applied: this ratio is outside the range the tool trusts.")).toBeVisible();
  });

  it("runs on the sample facts while the gateway does not serve the route", async () => {
    const fetch = vi.fn(async (url: string) =>
      url.endsWith("/v1/me")
        ? new Response(JSON.stringify({ kind: "human", name: "Demo approver", role: "approver", can_approve: true }))
        : new Response(JSON.stringify({ error: { code: "NO_ROUTE", message: "no" } }), { status: 404 }),
    );
    vi.stubGlobal("fetch", fetch);
    const api = createHttpApi("/api");
    renderApp("/settings/learned", api);

    expect(await screen.findByText("Washed potato 10 kg")).toBeVisible();
    expect(screen.getByText("Sample data")).toBeVisible();
    expect(fetch.mock.calls.some(([url]) => String(url).includes("/learned"))).toBe(false);
  });
});
