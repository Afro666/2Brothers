import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("Notification settings", () => {
  it("loads all four in-app notification choices", async () => {
    renderApp("/settings/notifications");

    expect(await screen.findByRole("checkbox", { name: "Approval waiting" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Cut-off in 2 hours" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Recall alert" })).toBeChecked();
    expect(screen.getByRole("checkbox", { name: "Order confirmed" })).toBeChecked();
    expect(screen.getByText(/E-mail delivery will be added later/)).toBeVisible();
  });

  it("saves the selected preferences with the right values", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const save = vi.spyOn(api, "saveNotificationPreferences");
    renderApp("/settings/notifications", api);

    await user.click(await screen.findByRole("checkbox", { name: "Cut-off in 2 hours" }));
    await user.click(screen.getByRole("checkbox", { name: "Order confirmed" }));
    await user.click(screen.getByRole("button", { name: "Save notifications" }));

    expect(save).toHaveBeenCalledWith({
      approvalWaiting: true,
      cutoffTwoHours: false,
      recallAlert: true,
      orderConfirmed: false,
    }, "human");
    expect(await screen.findByText("Notification preferences saved")).toBeVisible();
    expect((await api.getNotificationPreferences()).cutoffTwoHours).toBe(false);
  });

  it("shows save failures inline", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    vi.spyOn(api, "saveNotificationPreferences").mockRejectedValue(new Error("Preferences could not be saved."));
    renderApp("/settings/notifications", api);

    await screen.findByRole("checkbox", { name: "Approval waiting" });
    await user.click(screen.getByRole("button", { name: "Save notifications" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Preferences could not be saved.");
  });

  it("is read-only for a non-approver", async () => {
    const api = createMockApi();
    vi.spyOn(api, "getSession").mockResolvedValue({ name: "Viewer", email: "viewer@demo.kitchen", role: "viewer", canApprove: false, kind: "human" });
    renderApp("/settings/notifications", api);

    expect(await screen.findByRole("checkbox", { name: "Approval waiting" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Recall alert" })).toBeDisabled();
    expect(screen.getByText("Only an approver can change notification preferences.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Save notifications" })).not.toBeInTheDocument();
  });

  it("explains when an approver cannot save because the gateway has no route", async () => {
    const api = Object.assign(createMockApi(), { live: new Set(["getNotificationPreferences" as const]) });
    renderApp("/settings/notifications", api);

    expect(await screen.findByText("Saving notification preferences is not available on this server yet; the choices below are sample data.")).toBeVisible();
    expect(screen.getByRole("checkbox", { name: "Approval waiting" })).toBeDisabled();
    expect(screen.queryByText("Only an approver can change notification preferences.")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save notifications" })).not.toBeInTheDocument();
  });
});
