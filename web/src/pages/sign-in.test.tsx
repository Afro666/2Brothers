import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";
import { renderApp } from "@/test/render";

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

describe("authentication", () => {
  it("shows only sign-in to a signed-out visitor", async () => {
    renderApp("/approvals", createMockApi({ signedOut: true }));
    expect(await screen.findByRole("heading", { name: "Sign in to Kitchen Buyer" })).toBeVisible();
    expect(screen.queryByRole("link", { name: "Back to the demo" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open menu" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Approvals" })).not.toBeInTheDocument();
  });

  it("links back to Home from the open demo", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/sign-in", createMockApi());
    const back = await screen.findByRole("link", { name: "Back to the demo" });
    expect(back).toHaveAttribute("href", "/");
    await user.click(back);
    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    expect(router.state.location.pathname).toBe("/");
  });

  it("signs in from a demo account button and lands on Home", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/sign-in", createMockApi({ signedOut: true }));
    await user.click(await screen.findByRole("button", { name: "Sign in as Buyer" }));
    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    expect(router.state.location.pathname).toBe("/");
  });

  it("shows the form in the open demo, signs in, and returns to the open demo on sign out", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const getSession = vi.spyOn(api, "getSession");
    const signOut = vi.spyOn(api, "signOut");
    const { router } = renderApp("/sign-in", api);

    expect(await screen.findByRole("heading", { name: "Sign in to Kitchen Buyer" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: "Sign in as Buyer" }));
    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
    expect(screen.queryByTestId("open-demo-note")).not.toBeInTheDocument();

    await user.click((await screen.findAllByRole("button", { name: "Sign out" }))[0]);

    expect(await screen.findByTestId("open-demo-note")).toBeVisible();
    expect(screen.getAllByRole("link", { name: "Sign in" }).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Sign out" })).not.toBeInTheDocument();
    expect(signOut).toHaveBeenCalledOnce();
    expect(getSession).toHaveBeenCalledTimes(2);
    expect(router.state.location.pathname).toBe("/");
  });

  it("after sign-out a failed session read shows the error, not the sign-in page", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    await api.signIn("buyer@demo.kitchen", "demo-kitchen-2026");
    const getSession = vi.spyOn(api, "getSession");
    const { router } = renderApp("/", api);
    const signOut = (await screen.findAllByRole("button", { name: "Sign out" }))[0];
    getSession.mockRejectedValueOnce(new ApiError("GATEWAY_ERROR", "The gateway answered 503.", {}, 503));

    await user.click(signOut);

    expect(await screen.findByText("The gateway answered 503.")).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Sign in to Kitchen Buyer" })).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByTestId("open-demo-note")).toBeVisible();
    expect(router.state.location.pathname).toBe("/");
  });

  it("shows the gateway error for a wrong password", async () => {
    const user = userEvent.setup();
    renderApp("/", createMockApi({ signedOut: true }));
    await user.type(await screen.findByLabelText("Email"), "buyer@demo.kitchen");
    await user.type(screen.getByLabelText("Password"), "not-the-password");
    await user.click(screen.getByRole("button", { name: /^Sign in$/ }));
    expect(await screen.findByRole("alert")).toHaveTextContent("wrong email or password");
    expect(screen.getByRole("heading", { name: "Sign in to Kitchen Buyer" })).toBeVisible();
  });

  it("returns to sign-in after signing out", async () => {
    const user = userEvent.setup();
    const api = createMockApi({ signedOut: true });
    await api.signIn("buyer@demo.kitchen", "demo-kitchen-2026");
    const { router } = renderApp("/", api);
    await user.click((await screen.findAllByRole("button", { name: "Sign out" }))[0]);
    expect(await screen.findByRole("heading", { name: "Sign in to Kitchen Buyer" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Open menu" })).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it.each([
    ["a network failure", new ApiError("NETWORK", "Could not reach the gateway.")],
    ["an expired gateway session", new ApiError("UNAUTHENTICATED", "Sign in first", {}, 401)],
  ])("returns to sign-in without an error after sign-out fails with %s", async (_case, error) => {
    const user = userEvent.setup();
    const api = createMockApi({ signedOut: true });
    await api.signIn("buyer@demo.kitchen", "demo-kitchen-2026");
    api.signOut = vi.fn().mockRejectedValue(error);
    const { router } = renderApp("/", api);

    await user.click((await screen.findAllByRole("button", { name: "Sign out" }))[0]);

    expect(await screen.findByRole("heading", { name: "Sign in to Kitchen Buyer" })).toBeVisible();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Open menu" })).not.toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/sign-in");
  });

  it("disables approval for a viewer account and explains why", async () => {
    const user = userEvent.setup();
    const { router } = renderApp("/sign-in", createMockApi({ signedOut: true }));
    await user.click(await screen.findByRole("button", { name: "Sign in as Valio planner" }));
    await router.navigate({ to: "/approvals" });
    // A disabled Approve names no total (#1227); the totals block still does.
    const approveButtons = await screen.findAllByRole("button", { name: "Approve" });
    expect(approveButtons.length).toBeGreaterThan(0);
    expect(approveButtons.every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    const rejectButtons = screen.getAllByRole("button", { name: "Reject" });
    expect(rejectButtons.length).toBeGreaterThan(0);
    expect(rejectButtons.every((button) => (button as HTMLButtonElement).disabled)).toBe(true);
    expect(screen.getAllByText("Your account cannot approve or reject orders.")[0]).toBeVisible();
  });

  it("offers retry after a session error without showing the app", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const getSession = api.getSession;
    api.getSession = vi.fn()
      .mockRejectedValueOnce(new ApiError("NETWORK", "Could not reach the gateway."))
      .mockImplementation(() => getSession.call(api));
    renderApp("/", api);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the gateway.");
    expect(screen.queryByRole("button", { name: "Open menu" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(await screen.findByText("Waiting for your approval")).toBeVisible();
  });

  it("restores the chef view for a chef session even when storage says buyer", async () => {
    localStorage.setItem("purchasing-role", "buyer");
    const api = createMockApi();
    api.getSession = async () => ({
      kind: "human",
      name: "Restored chef",
      email: "chef@example.com",
      role: "chef",
      canApprove: false,
    });
    renderApp("/", api);

    const picker = (await screen.findAllByRole("radiogroup", { name: "Your role" }))[0]!;
    // #2005: one Kitchen option for chef and approver; no option is called Buyer.
    expect(within(picker).getByRole("radio", { name: "Kitchen" })).toBeChecked();
    expect(within(picker).queryByRole("radio", { name: "Buyer" })).not.toBeInTheDocument();
    expect(localStorage.getItem("purchasing-role")).toBe("chef");
  });

  it("uses the read-only chef view for a generic viewer", async () => {
    localStorage.setItem("purchasing-role", "valio_planner");
    const api = createMockApi();
    api.getSession = async () => ({
      kind: "human",
      name: "Kitchen viewer",
      email: "viewer@example.com",
      role: "viewer",
      canApprove: false,
    });
    renderApp("/", api);

    const picker = (await screen.findAllByRole("radiogroup", { name: "Your role" }))[0]!;
    // #2005: one Kitchen option for chef and approver; no option is called Buyer.
    expect(within(picker).getByRole("radio", { name: "Kitchen" })).toBeChecked();
    expect(within(picker).queryByRole("radio", { name: "Buyer" })).not.toBeInTheDocument();
    expect(screen.getByText("What needs you today.")).toBeVisible();
    expect(screen.queryByText("Where demand may outrun supply.")).not.toBeInTheDocument();
  });

  it("treats an HTTP 401 with another error code as signed out", async () => {
    const api = createMockApi();
    api.getSession = async () => {
      throw new ApiError("SESSION_EXPIRED", "The session expired.", {}, 401);
    };
    renderApp("/approvals", api);

    expect(await screen.findByRole("heading", { name: "Sign in to Kitchen Buyer" })).toBeVisible();
    expect(screen.queryByRole("button", { name: "Open menu" })).not.toBeInTheDocument();
  });
});
