import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { mapKitchenSettings } from "@/api/map-planning";
import { EU_ALLERGENS } from "@/lib/allergens";
import { renderApp } from "@/test/render";

describe("Ordering engine settings", () => {
  beforeEach(() => localStorage.clear());

  it("renders the kitchen defaults", async () => {
    renderApp("/settings/engine", createMockApi());

    expect(await screen.findByRole("heading", { level: 1, name: "Settings" })).toBeInTheDocument();
    expect(await screen.findByLabelText("A — Menu-critical")).toHaveValue(97.5);
    expect(screen.getByLabelText("B — Regular")).toHaveValue(95);
    expect(screen.getByLabelText("C — Nice to have")).toHaveValue(90);
    expect(screen.getByLabelText("Maximum scaling factor")).toHaveValue(1.8);
    expect(screen.getByLabelText("Per order (ex VAT, €)")).toHaveValue(1500);
    expect(screen.getByRole("checkbox", { name: "Peanuts (AP)" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Tree nuts (AN)" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Sesame (AS)" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
  });

  it("labels the engine's defaults the gateway sent, and only while they are unchanged", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    // The live answer's shape: only what the kitchen set, plus the engine's `defaults`.
    const live = mapKitchenSettings({
      standing_orders: { "463335": "110" },
      excluded_allergens: ["AP", "AN", "AS"],
      service_level: { A: "0.98" },
      defaults: {
        service_level: { A: "0.975", B: "0.95", C: "0.90" },
        max_cover_days: { fresh_dairy: 4, dry: 30 },
        stockout_cap: 1.8,
        budget_warning_order_eur: "1500",
        budget_warning_week_eur: "5000",
      },
    });
    api.getKitchenSettings = async () => structuredClone(live);
    renderApp("/settings/engine", api);

    expect(await screen.findByLabelText("A — Menu-critical")).toHaveValue(98);
    expect(screen.getByLabelText("B — Regular")).toHaveValue(95);
    expect(screen.getByLabelText("Maximum scaling factor")).toHaveValue(1.8);
    expect(screen.getByLabelText("Per order (ex VAT, €)")).toHaveValue(1500);
    // B, C, two cover rows, the cap and both budgets; not A, which the kitchen set.
    expect(screen.getAllByText("Engine default")).toHaveLength(7);

    const b = screen.getByLabelText("B — Regular");
    expect(b).toHaveAccessibleDescription("Engine default");
    expect(screen.getByLabelText("A — Menu-critical")).not.toHaveAccessibleDescription("Engine default");
    await user.clear(b);
    await user.type(b, "96");
    expect(screen.getAllByText("Engine default")).toHaveLength(6);
    expect(b).not.toHaveAccessibleDescription("Engine default");

    // The save names the defaults still untouched, so the adapter leaves them to the engine.
    const save = vi.spyOn(api, "saveKitchenSettings");
    await user.click(screen.getByRole("button", { name: "Save settings" }));
    await waitFor(() => expect(save).toHaveBeenCalledOnce());
    const sent = save.mock.calls[0][0].engineDefaults;
    expect(sent).toContain("serviceLevelPercent.C");
    expect(sent).not.toContain("serviceLevelPercent.B");
  });

  it("lists allergens by name in the same order as Kitchen settings", async () => {
    renderApp("/settings/engine", createMockApi());

    await screen.findByRole("checkbox", { name: "Peanuts (AP)" });
    const boxes = screen.getAllByRole("checkbox");
    expect(boxes).toHaveLength(EU_ALLERGENS.length);
    EU_ALLERGENS.forEach(({ code, name }, index) => expect(boxes[index]).toHaveAccessibleName(`${name} (${code})`));
  });

  it("saves a service level and writes an audit event", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const { router } = renderApp("/settings/engine", api);

    const input = await screen.findByLabelText("A — Menu-critical");
    await user.clear(input);
    await user.type(input, "98");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(await screen.findByTestId("settings-saved-toast")).toHaveTextContent("Settings saved");
    await waitFor(async () => {
      expect((await api.getKitchenSettings()).serviceLevelPercent.A).toBe(98);
      expect((await api.listAudit()).at(-1)).toMatchObject({
        kind: "settings",
        reason: "Service level A: 97.5 % to 98 %",
      });
    });
    await router.navigate({ to: "/audit" });
    expect(await screen.findByRole("heading", { level: 1, name: "Activity log" })).toBeInTheDocument();
    expect(await screen.findByText("Kitchen settings updated")).toBeInTheDocument();
    expect(screen.getByText("Service level A: 97.5 % to 98 %")).toBeInTheDocument();
  });

  it("shows an out-of-range API error and keeps the typed value", async () => {
    const user = userEvent.setup();
    renderApp("/settings/engine", createMockApi());

    const input = await screen.findByLabelText("A — Menu-critical");
    await user.clear(input);
    await user.type(input, "100");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Service level A must be between 50 and 99.9 percent.");
    expect(input).toHaveValue(100);
  });

  it("saves an empty budget warning as null", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/settings/engine", api);

    const input = await screen.findByLabelText("Per order (ex VAT, €)");
    await user.clear(input);
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    await screen.findByTestId("settings-saved-toast");
    expect((await api.getKitchenSettings()).budgetWarningPerOrderExVat).toBeNull();
  });

  it("resets edited values to the loaded settings", async () => {
    const user = userEvent.setup();
    renderApp("/settings/engine", createMockApi());

    const input = await screen.findByLabelText("A — Menu-critical");
    await user.clear(input);
    await user.type(input, "98");
    await user.click(screen.getByRole("button", { name: "Reset changes" }));

    expect(input).toHaveValue(97.5);
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
  });

  it("keeps focus while typing a new cover category", async () => {
    const user = userEvent.setup();
    renderApp("/settings/engine", createMockApi());

    await user.click(await screen.findByRole("button", { name: "Add category" }));
    const inputs = screen.getAllByLabelText("Category");
    const input = inputs[inputs.length - 1];
    await user.click(input);
    await user.type(input, "Meat");

    expect(input).toHaveValue("Meat");
    expect(input).toHaveFocus();
  });

  it("offers Remove only on cover rows added in this edit", async () => {
    const user = userEvent.setup();
    renderApp("/settings/engine", createMockApi());

    // Loaded rows: the gateway merges cover rules, so they cannot be removed.
    expect(await screen.findAllByLabelText("Category")).toHaveLength(3);
    expect(screen.queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Add category" }));
    expect(screen.getAllByLabelText("Category")).toHaveLength(4);
    await user.click(screen.getByRole("button", { name: "Remove category" }));

    expect(screen.getAllByLabelText("Category")).toHaveLength(3);
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
  });
});
