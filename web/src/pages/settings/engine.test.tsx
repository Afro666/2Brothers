import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
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
    expect(screen.getByRole("checkbox", { name: "AP Peanuts" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "AN Tree nuts" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "AS Sesame" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save settings" })).toBeDisabled();
  });

  it("saves a service level and writes an audit event", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const { router } = renderApp("/settings/engine", api);

    const input = await screen.findByLabelText("A — Menu-critical");
    await user.clear(input);
    await user.type(input, "98");
    await user.click(screen.getByRole("button", { name: "Save settings" }));

    expect(await screen.findByRole("status")).toHaveTextContent("Settings saved");
    await waitFor(async () => {
      expect((await api.getKitchenSettings()).serviceLevelPercent.A).toBe(98);
      expect((await api.listAudit()).at(-1)).toMatchObject({
        kind: "settings",
        reason: "Service level A: 97.5 % to 98 %",
      });
    });
    await router.navigate({ to: "/audit" });
    expect(await screen.findByRole("heading", { level: 1, name: "Audit log" })).toBeInTheDocument();
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

    await screen.findByRole("status");
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
});
