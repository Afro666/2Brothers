import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("Developer settings", () => {
  it("loads webhooks, diagnostics and a new-tab OpenAPI docs link", async () => {
    const api = createMockApi();
    renderApp("/settings/developer", api);

    expect(await screen.findByText("https://hooks.example.test/kitchen")).toBeVisible();
    const docs = screen.getByRole("link", { name: "OpenAPI docs" });
    expect(docs).toHaveAttribute("href", `${window.location.origin}/api/docs`);
    expect(docs).toHaveAttribute("target", "_blank");
    expect(screen.getByText("Page data: mock")).toBeVisible();
    expect(screen.getByText("Valio API: unknown")).toBeVisible();
    expect(screen.getByText("not connected (sample data)")).toBeVisible();
    expect(screen.getAllByText("unknown", { selector: "dd" })).toHaveLength(2);
    await expect(api.getGatewayHealth()).resolves.toEqual({ status: "not connected (sample data)", valioMode: "unknown" });
    const calls = screen.getByRole("list", { name: "Recent API calls" });
    expect(within(calls).getAllByRole("listitem")).toHaveLength(3);
    expect(within(calls).getByText("201")).toBeVisible();
  });

  it("creates a webhook, reveals its secret once and sends a test", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const create = vi.spyOn(api, "createWebhook");
    const test = vi.spyOn(api, "testWebhook");
    renderApp("/settings/developer", api);

    await user.type(await screen.findByLabelText("Webhook URL"), "https://hooks.example.com/new");
    await user.click(screen.getByRole("button", { name: "Create webhook" }));
    expect(create).toHaveBeenCalledWith({
      url: "https://hooks.example.com/new",
      events: ["proposal.ready", "recall.alert"],
    }, "human");
    expect(await screen.findByText("whsec_demo_0003", { selector: "code" })).toBeVisible();

    await user.click(screen.getByRole("button", { name: "Send test to hook-demo-1" }));
    expect(test).toHaveBeenCalledWith("hook-demo-1", "human");
    expect(await screen.findByText(/Last test: delivered, HTTP 200, 1 attempt/)).toBeVisible();
  });

  it("validates the URL and selected events before calling the Api", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const create = vi.spyOn(api, "createWebhook");
    renderApp("/settings/developer", api);

    await user.click(await screen.findByRole("button", { name: "Create webhook" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter an https webhook URL");
    const url = screen.getByLabelText("Webhook URL");
    await user.type(url, "http://insecure.example.com/hook");
    await user.click(screen.getByRole("button", { name: "Create webhook" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter an https webhook URL");

    await user.clear(url);
    await user.type(url, "http://localhost:8000/hook");
    await user.click(screen.getByRole("button", { name: "Create webhook" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Enter an https webhook URL");

    await user.clear(url);
    await user.type(url, "https://hooks.example.com/new");
    await user.click(screen.getByRole("checkbox", { name: "proposal.ready" }));
    await user.click(screen.getByRole("checkbox", { name: "recall.alert" }));
    await user.click(screen.getByRole("button", { name: "Create webhook" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Select at least one webhook event");
    expect(create).not.toHaveBeenCalled();
  });

  it("hides webhook writes and tests from a non-approver", async () => {
    const api = createMockApi();
    vi.spyOn(api, "getSession").mockResolvedValue({ name: "Viewer", email: "viewer@demo.kitchen", role: "viewer", canApprove: false, kind: "human" });
    renderApp("/settings/developer", api);

    expect(await screen.findByText("https://hooks.example.test/kitchen")).toBeVisible();
    expect(screen.getByText("Only an approver can create, test or remove webhooks.")).toBeVisible();
    expect(screen.queryByLabelText("Webhook URL")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create webhook" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Send test to/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Remove/ })).not.toBeInTheDocument();
  });

  it("lets an approver remove a webhook after a confirm and reloads the list", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const remove = vi.spyOn(api, "deleteWebhook");
    const confirm = vi.spyOn(window, "confirm").mockReturnValueOnce(false).mockReturnValueOnce(true);
    renderApp("/settings/developer", api);

    const button = await screen.findByRole("button", { name: "Remove hook-demo-1" });
    await user.click(button);
    expect(remove).not.toHaveBeenCalled();
    expect(screen.getByText("https://hooks.example.test/kitchen")).toBeVisible();

    await user.click(button);
    expect(remove).toHaveBeenCalledWith("hook-demo-1", "human");
    expect(await screen.findByText("No webhooks")).toBeVisible();
    expect(screen.queryByText("https://hooks.example.test/kitchen")).not.toBeInTheDocument();
    expect(confirm).toHaveBeenCalledTimes(2);
    confirm.mockRestore();
  });
});
