import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("Kitchen settings", () => {
  it("loads the profile and the shared hard allergen rules", async () => {
    renderApp("/settings/kitchen");

    expect(await screen.findByLabelText("Kitchen name")).toHaveValue("Kuu School Kitchen");
    expect(screen.getByLabelText("Kitchen type")).toHaveTextContent("School");
    expect(screen.getByLabelText("Address")).toHaveValue("Koulukatu 12, 00100 Helsinki, Finland");
    expect(screen.getByLabelText("Timezone")).toHaveValue("Europe/Helsinki");
    expect(screen.getByLabelText("Delivery address")).toHaveValue(
      "Kuu School, rear delivery entrance, Koulukatu 14, Helsinki",
    );
    expect(screen.getByRole("checkbox", { name: "Peanuts (AP)" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Gluten cereals (AW)" })).not.toBeChecked();
    expect(screen.getByRole("link", { name: "ordering engine settings" })).toHaveAttribute("href", "/settings/engine");
  });

  it("saves the profile and allergen rules through their Api methods", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const saveProfile = vi.spyOn(api, "saveKitchenProfile");
    const saveSettings = vi.spyOn(api, "saveKitchenSettings");
    renderApp("/settings/kitchen", api);

    const name = await screen.findByLabelText("Kitchen name");
    await user.clear(name);
    await user.type(name, "  Coeliac School  ");
    await user.click(screen.getByRole("button", { name: "Save profile" }));
    expect(saveProfile).toHaveBeenCalledWith(expect.objectContaining({ name: "Coeliac School", type: "school" }), "human");
    expect(await screen.findByText("Kitchen profile saved")).toBeVisible();

    await user.click(screen.getByRole("checkbox", { name: "Gluten cereals (AW)" }));
    await user.click(screen.getByRole("button", { name: "Save allergen rules" }));
    expect(saveSettings).toHaveBeenCalledWith(expect.objectContaining({ excludedAllergens: ["AP", "AN", "AS", "AW"] }), "human");
    expect((await api.getKitchenSettings()).excludedAllergens).toContain("AW");
    expect(await screen.findByText("Allergen rules saved")).toBeVisible();
  });

  it("validates required fields and the timezone before saving", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const save = vi.spyOn(api, "saveKitchenProfile");
    renderApp("/settings/kitchen", api);

    const name = await screen.findByLabelText("Kitchen name");
    await user.clear(name);
    await user.click(screen.getByRole("button", { name: "Save profile" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Kitchen name is required.");

    await user.type(name, "School");
    const timezone = screen.getByLabelText("Timezone");
    await user.clear(timezone);
    await user.type(timezone, "Mars/Olympus");
    await user.click(screen.getByRole("button", { name: "Save profile" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("valid IANA timezone");
    expect(save).not.toHaveBeenCalled();
  });

  it("is read-only for a non-approver", async () => {
    const api = createMockApi();
    vi.spyOn(api, "getSession").mockResolvedValue({
      name: "Viewer",
      email: "viewer@demo.kitchen",
      role: "viewer",
      canApprove: false,
      kind: "human",
    });
    renderApp("/settings/kitchen", api);

    expect(await screen.findByLabelText("Kitchen name")).toBeDisabled();
    expect(screen.getByLabelText("Kitchen type")).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Gluten cereals (AW)" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Save profile" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save allergen rules" })).not.toBeInTheDocument();
  });
});
