import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ApiError, type ApiToken } from "@/api/types";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

async function createToken(user: ReturnType<typeof userEvent.setup>, name: string) {
  const input = await screen.findByLabelText("Token name");
  await user.clear(input);
  await user.type(input, name);
  await user.click(screen.getByRole("button", { name: "Create token" }));
}

describe("API & MCP token settings", () => {
  it("shows a created secret only until the next create, and puts the new secret in both commands", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/settings/tokens", api);

    await createToken(user, "Claude one");
    const first = await screen.findByText("tkb_demo_0001", { selector: "code" });
    expect(first).toBeVisible();
    expect(screen.getByText("This is the only time the token is shown.")).toBeVisible();
    expect(screen.getByLabelText("MCP: Claude Code")).toHaveTextContent(
      `claude mcp add --transport http kitchen-buyer ${window.location.origin}/gateway/mcp --header "Authorization: Bearer tkb_demo_0001"`,
    );
    expect(screen.getByLabelText("HTTP: list proposals (needs kitchen:read)")).toHaveTextContent(
      `curl -H "Authorization: Bearer tkb_demo_0001" ${window.location.origin}/gateway/v1/kitchens/demo-kitchen/proposals`,
    );
    expect(
      screen.getByRole("link", { name: `Agent instructions: ${window.location.origin}/llms.txt` }),
    ).toHaveAttribute("href", `${window.location.origin}/llms.txt`);
    expect(
      screen.getByRole("link", { name: `Agent card: ${window.location.origin}/.well-known/agent-card.json` }),
    ).toHaveAttribute("href", `${window.location.origin}/.well-known/agent-card.json`);

    await createToken(user, "Claude two");
    expect(await screen.findByText("tkb_demo_0002", { selector: "code" })).toBeVisible();
    expect(screen.queryByText("tkb_demo_0001", { selector: "code" })).not.toBeInTheDocument();
    expect(screen.getByLabelText("MCP: Claude Code")).toHaveTextContent("tkb_demo_0002");
    expect(screen.getByLabelText("HTTP: list proposals (needs kitchen:read)")).toHaveTextContent("tkb_demo_0002");
    expect((await api.listApiTokens()).every((token) => !("token" in token))).toBe(true);
  });

  it("copies the token and each ready command with the clipboard", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    const user = userEvent.setup();
    Object.defineProperty(navigator, "clipboard", { configurable: true, value: { writeText } });
    renderApp("/settings/tokens");

    await user.click(await screen.findByRole("button", { name: "Copy MCP command" }));
    expect(writeText).toHaveBeenCalledWith(
      `claude mcp add --transport http kitchen-buyer ${window.location.origin}/gateway/mcp --header "Authorization: Bearer <token>"`,
    );
    await user.click(screen.getByRole("button", { name: "Copy curl command" }));
    expect(writeText).toHaveBeenLastCalledWith(
      `curl -H "Authorization: Bearer <token>" ${window.location.origin}/gateway/v1/kitchens/demo-kitchen/proposals`,
    );
    await createToken(user, "Claude");
    await user.click(await screen.findByRole("button", { name: "Copy token" }));
    expect(writeText).toHaveBeenLastCalledWith("tkb_demo_0001");
  });

  it("asks for confirmation before revoking and calls the API", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    renderApp("/settings/tokens", api);
    const revoke = vi.spyOn(api, "revokeApiToken");

    await user.click(await screen.findByRole("button", { name: "Revoke Kitchen reader" }));
    expect(revoke).not.toHaveBeenCalled();
    const dialog = screen.getByRole("dialog", { name: "Revoke Kitchen reader?" });
    expect(within(dialog).getByText(/immediately lose access/)).toBeVisible();
    await user.click(within(dialog).getByRole("button", { name: "Revoke token" }));
    await waitFor(() => expect(revoke).toHaveBeenCalledWith("token-demo-reader"));
    expect(await screen.findByText("Revoked", { selector: "span" })).toBeVisible();
  });

  it("does not show token management to a non-approver", async () => {
    const api = createMockApi();
    vi.spyOn(api, "getSession").mockResolvedValue({
      kind: "human",
      name: "A viewer",
      email: "viewer@demo.kitchen",
      role: "viewer",
      canApprove: false,
    });
    renderApp("/settings/tokens", api);

    expect(await screen.findByText("Kitchen reader")).toBeVisible();
    expect(screen.queryByLabelText("Token name")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Create token" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Revoke Kitchen reader/ })).not.toBeInTheDocument();
    expect(screen.getByText("Only an approver can create or revoke API tokens.")).toBeVisible();
  });

  it("validates the trimmed name, length and at least one scope before calling the API", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const create = vi.spyOn(api, "createApiToken");
    renderApp("/settings/tokens", api);

    await user.click(await screen.findByRole("button", { name: "Create token" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("name between 1 and 80 characters");
    await user.type(screen.getByLabelText("Token name"), "x".repeat(81));
    await user.click(screen.getByRole("button", { name: "Create token" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("name between 1 and 80 characters");
    await user.clear(screen.getByLabelText("Token name"));
    await user.type(screen.getByLabelText("Token name"), "Kitchen agent");
    await user.click(screen.getByRole("checkbox", { name: /Read kitchen/ }));
    await user.click(screen.getByRole("checkbox", { name: /Propose orders/ }));
    await user.click(screen.getByRole("button", { name: "Create token" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Select at least one token scope");
    expect(create).not.toHaveBeenCalled();
    expect(screen.queryByRole("checkbox", { name: /approve/i })).not.toBeInTheDocument();
  });

  it("maps list permission denials to a plain explanation", async () => {
    const api = createMockApi();
    vi.spyOn(api, "listApiTokens").mockRejectedValue(new ApiError("ROLE_REQUIRED", "approver required", {}, 403));
    renderApp("/settings/tokens", api);

    expect(await screen.findByText("Your account does not have permission to view API tokens.")).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("distinguishes a token that was never used from an absent last-used field", async () => {
    const api = createMockApi();
    const known: ApiToken = {
      id: "unknown-usage",
      name: "Older gateway token",
      scopes: ["kitchen:read"],
      prefix: "tkb_older",
      createdAt: "2026-10-01T12:00:00Z",
      createdBy: "buyer",
      revokedAt: null,
    };
    const existing = await api.listApiTokens();
    vi.spyOn(api, "listApiTokens").mockResolvedValue([known, ...existing]);
    renderApp("/settings/tokens", api);

    expect(await screen.findByText("Older gateway token")).toBeVisible();
    expect(screen.getByText("unknown")).toBeVisible();
    expect(screen.getByText("never")).toBeVisible();
  });
});
