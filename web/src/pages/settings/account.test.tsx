import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("Account settings", () => {
  it("changes a valid password and shows a success toast", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    await api.signIn("buyer@demo.kitchen", "demo-kitchen-2026");
    renderApp("/settings/account", api);
    await user.type(await screen.findByLabelText("Current password"), "demo-kitchen-2026");
    await user.type(screen.getByLabelText("New password"), "new-demo-password");
    await user.type(screen.getByLabelText("Repeat new password"), "new-demo-password");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByText("Password changed")).toBeVisible();
    await expect(api.signIn("buyer@demo.kitchen", "demo-kitchen-2026")).rejects.toMatchObject({ code: "INVALID_LOGIN" });
    await expect(api.signIn("buyer@demo.kitchen", "new-demo-password")).resolves.toMatchObject({ role: "approver" });
  });

  it("shows a mismatch error before calling the gateway", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const changePassword = vi.spyOn(api, "changePassword");
    renderApp("/settings/account", api);
    await user.type(await screen.findByLabelText("Current password"), "demo-kitchen-2026");
    await user.type(screen.getByLabelText("New password"), "new-demo-password");
    await user.type(screen.getByLabelText("Repeat new password"), "different-password");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Passwords do not match.");
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("shows a too-short error before calling the gateway", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const changePassword = vi.spyOn(api, "changePassword");
    renderApp("/settings/account", api);
    await user.type(await screen.findByLabelText("Current password"), "demo-kitchen-2026");
    await user.type(screen.getByLabelText("New password"), "short");
    await user.type(screen.getByLabelText("Repeat new password"), "short");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("at least 10 characters");
    expect(changePassword).not.toHaveBeenCalled();
  });

  it("shows the gateway error when the current password is wrong", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    await api.signIn("buyer@demo.kitchen", "demo-kitchen-2026");
    renderApp("/settings/account", api);
    await user.type(await screen.findByLabelText("Current password"), "not-the-password");
    await user.type(screen.getByLabelText("New password"), "new-demo-password");
    await user.type(screen.getByLabelText("Repeat new password"), "new-demo-password");
    await user.click(screen.getByRole("button", { name: "Change password" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("the current password is wrong");
  });
});
