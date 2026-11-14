import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApiError, type Api } from "@/api/types";
import { desktopConfig } from "@/pages/settings/approve-chat";
import { renderApp } from "@/test/render";

async function signedIn(email = "buyer@demo.kitchen") {
  const api = createMockApi();
  await api.signIn(email, "demo-kitchen-2026");
  return api;
}

afterEach(() => vi.restoreAllMocks());

describe("Approve from chat settings", () => {
  it("creates a shared open-demo token in the open demo and shows it once", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const create = vi.spyOn(api, "createApprovalToken");
    renderApp("/settings/approve-chat", api);

    expect(await screen.findByText("Open demo: these tokens are shared")).toBeVisible();
    expect(screen.getByText(/every open-demo visitor sees its prefix and times and can revoke it/)).toBeVisible();
    expect(within(screen.getByTestId("approve-chat-open-demo")).getByRole("link", { name: "Sign in" })).toHaveAttribute(
      "href",
      "/sign-in",
    );
    expect(await screen.findByText("No approval tokens yet")).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Create approval token" }));

    expect(create).toHaveBeenCalledWith({ hours: 8 });
    expect(await screen.findByText("tka_demo_0001", { selector: "code" })).toBeVisible();
    const config = screen.getByLabelText("claude_desktop_config.json");
    expect(config.textContent).toBe(desktopConfig(`${window.location.origin}/gateway/mcp`, "tka_demo_0001"));
    const list = await screen.findByRole("list", { name: "Approval tokens" });
    expect(within(list).getByText("open-demo")).toBeVisible();
    expect(within(list).queryByText(/tka_demo_0001/)).not.toBeInTheDocument();
  });

  it("never calls the mock create when gateway mode does not serve it", async () => {
    const mock = await signedIn();
    const api: Api = { ...mock, live: new Set<keyof Api>() };
    const create = vi.spyOn(api, "createApprovalToken");
    renderApp("/settings/approve-chat", api);

    expect(await screen.findByRole("alert")).toHaveTextContent("The gateway does not serve approval token creation.");
    expect(screen.queryByRole("button", { name: "Create approval token" })).not.toBeInTheDocument();
    expect(create).not.toHaveBeenCalled();
  });

  it("the mock keeps open-demo tokens and a person's tokens apart, like the gateway", async () => {
    const api = createMockApi();
    const demo = await api.createApprovalToken({ hours: 8 });
    expect(demo.person).toBe("open-demo");
    await api.signIn("buyer@demo.kitchen", "demo-kitchen-2026");
    expect(await api.listApprovalTokens()).toEqual([]);
    await expect(api.revokeApprovalToken(demo.id)).rejects.toMatchObject({ status: 404, code: "TOKEN_NOT_FOUND" });
    const mine = await api.createApprovalToken({ hours: 8 });
    await api.signOut();
    expect((await api.listApprovalTokens()).map((row) => row.id)).toEqual([demo.id]);
    await expect(api.revokeApprovalToken(mine.id)).rejects.toMatchObject({ status: 404, code: "TOKEN_NOT_FOUND" });
    expect((await api.revokeApprovalToken(demo.id)).revokedAt).not.toBeNull();
  });

  it("creates a token for 8 hours by default, shows it once in the Desktop config, and lists it without the value", async () => {
    const user = userEvent.setup();
    const api = await signedIn();
    const create = vi.spyOn(api, "createApprovalToken");
    renderApp("/settings/approve-chat", api);

    const hours = await screen.findByLabelText("Valid for (hours)");
    expect(hours).toHaveValue(8);
    await user.click(screen.getByRole("button", { name: "Create approval token" }));

    expect(create).toHaveBeenCalledWith({ hours: 8 });
    expect(await screen.findByText("tka_demo_0001", { selector: "code" })).toBeVisible();
    expect(screen.getByText("This is the only time the token is shown.")).toBeVisible();
    const config = screen.getByLabelText("claude_desktop_config.json");
    // The config never carries the token: the token is shown once, in its own box.
    expect(config.textContent).toBe(desktopConfig(`${window.location.origin}/gateway/mcp`, "<token>"));
    expect(config.textContent).not.toContain("tka_demo_0001");
    expect(config).toHaveClass("max-w-full", "overflow-x-auto");
    expect(config.querySelector("code")).toHaveClass("whitespace-pre-wrap", "break-all");
    expect(screen.getByText(/mcp-remote sends AUTH_HEADER as the Authorization header/)).toBeVisible();
    expect(screen.getByRole("link", { name: `${window.location.origin}/.well-known/agent-card.json` })).toBeVisible();
    expect(screen.getByText(/must show you the total and get your clear yes/)).toBeVisible();

    const list = await screen.findByRole("list", { name: "Approval tokens" });
    expect(within(list).getByText("buyer@demo.kitchen")).toBeVisible();
    expect(within(list).getByText("Active")).toBeVisible();
    expect(within(list).getByText("never")).toBeVisible();
    expect(within(list).queryByText(/tka_demo_0001/)).not.toBeInTheDocument();
    expect((await api.listApprovalTokens()).every((row) => !("token" in row))).toBe(true);
  });

  it("sends the chosen hours and refuses a number outside 1 to 24 before calling the gateway", async () => {
    const user = userEvent.setup();
    const api = await signedIn();
    const create = vi.spyOn(api, "createApprovalToken");
    renderApp("/settings/approve-chat", api);

    const hours = await screen.findByLabelText("Valid for (hours)");
    await user.clear(hours);
    await user.type(hours, "25");
    await user.click(screen.getByRole("button", { name: "Create approval token" }));
    expect(await screen.findByText("Choose a whole number of hours from 1 to 24.")).toBeVisible();
    expect(create).not.toHaveBeenCalled();

    await user.clear(hours);
    await user.type(hours, "2");
    await user.click(screen.getByRole("button", { name: "Create approval token" }));
    await waitFor(() => expect(create).toHaveBeenCalledWith({ hours: 2 }));
    const expires = Date.parse((await api.listApprovalTokens())[0].expiresAt);
    expect(expires - Date.now()).toBeLessThanOrEqual(2 * 3_600_000);
    expect(expires - Date.now()).toBeGreaterThan(2 * 3_600_000 - 60_000);
  });

  it("copies the token and the config", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    renderApp("/settings/approve-chat", await signedIn());

    await user.click(await screen.findByRole("button", { name: "Create approval token" }));
    await user.click(await screen.findByRole("button", { name: "Copy approval token" }));
    expect(writeText).toHaveBeenLastCalledWith("tka_demo_0001");
    await user.click(screen.getByRole("button", { name: "Copy config" }));
    expect(writeText).toHaveBeenLastCalledWith(desktopConfig(`${window.location.origin}/gateway/mcp`, "<token>"));
  });

  it("revokes a token after a confirmation and hides the shown value", async () => {
    const user = userEvent.setup();
    const api = await signedIn();
    const revoke = vi.spyOn(api, "revokeApprovalToken");
    renderApp("/settings/approve-chat", api);

    await user.click(await screen.findByRole("button", { name: "Create approval token" }));
    await screen.findByText("tka_demo_0001", { selector: "code" });
    await user.click(await screen.findByRole("button", { name: "Revoke token tka_demo" }));
    expect(revoke).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Revoke approval token tka_demo?" });
    await user.click(within(dialog).getByRole("button", { name: "Revoke token" }));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("approval-token-demo-1"));
    expect(await screen.findByText("Revoked", { selector: "span" })).toBeVisible();
    expect(screen.queryByText("tka_demo_0001", { selector: "code" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke token tka_demo" })).not.toBeInTheDocument();
  });

  it("shows an expired token as expired, with its times, and offers no revoke", async () => {
    const api = await signedIn();
    vi.spyOn(api, "listApprovalTokens").mockResolvedValue([
      {
        id: "old",
        name: "chat",
        person: "buyer@demo.kitchen",
        prefix: "tka_old1",
        createdAt: "2026-11-01T08:00:00Z",
        createdBy: "buyer@demo.kitchen",
        expiresAt: "2026-11-01T16:00:00Z",
        lastUsedAt: "2026-11-01T09:30:00Z",
        revokedAt: null,
      },
    ]);
    renderApp("/settings/approve-chat", api);

    const list = await screen.findByRole("list", { name: "Approval tokens" });
    expect(within(list).getByText("Expired")).toBeVisible();
    expect(within(list).getByText("Expires")).toBeVisible();
    expect(within(list).queryByText("never")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Revoke token tka_old1" })).not.toBeInTheDocument();
  });

  it("offers no create to a chef and says why", async () => {
    const api = await signedIn("chef@demo.kitchen");
    vi.spyOn(api, "listApprovalTokens").mockRejectedValue(new ApiError("ROLE_REQUIRED", "approver only", {}, 403));
    renderApp("/settings/approve-chat", api);

    expect(await screen.findByText("Only an approver can create an approval token.")).toBeVisible();
    expect(await screen.findByText("Only an approver can see the approval tokens.")).toBeVisible();
    expect(screen.queryByRole("button", { name: "Create approval token" })).not.toBeInTheDocument();
  });

  it("shows the gateway's sign-in refusal in plain words", async () => {
    const user = userEvent.setup();
    const api = await signedIn();
    vi.spyOn(api, "createApprovalToken").mockRejectedValue(
      new ApiError("PERSONAL_TOKEN_NEEDS_SIGN_IN", "needs sign in", {}, 403),
    );
    renderApp("/settings/approve-chat", api);

    await user.click(await screen.findByRole("button", { name: "Create approval token" }));
    expect(await screen.findByText("A personal approval token needs your own signed-in account.")).toBeVisible();
  });

  it.each([
    new ApiError("PERSONAL_TOKEN_NEEDS_SIGN_IN", "needs sign in", {}, 403),
    new ApiError("GATEWAY_ERROR", "gateway failed", {}, 500),
    new ApiError("INVALID_RESPONSE", "the one-time approval token is missing"),
  ])("create failed: no token shown for $code", async (error) => {
    const user = userEvent.setup();
    const api = await signedIn();
    vi.spyOn(api, "createApprovalToken").mockRejectedValue(error);
    renderApp("/settings/approve-chat", api);

    await user.click(await screen.findByRole("button", { name: "Create approval token" }));

    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.queryByLabelText("New approval token")).not.toBeInTheDocument();
    expect(screen.queryByText("Approval token created")).not.toBeInTheDocument();
  });
});
