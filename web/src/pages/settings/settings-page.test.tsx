import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SETTINGS_SECTIONS } from "@/pages/settings/sections";
import { renderApp } from "@/test/render";

afterEach(() => {
  vi.unstubAllGlobals();
  localStorage.clear();
});

const sectionNav = () => screen.findByRole("navigation", { name: "Settings sections" });

describe("settings area", () => {
  it("lists every section at /settings", async () => {
    renderApp("/settings");
    const links = within(await sectionNav()).getAllByRole("link");
    expect(links.map((link) => link.textContent)).toEqual([
      "Account",
      "Appearance",
      "Kitchen",
      "Team",
      "Permissions",
      "API & MCP tokens",
      "Notifications",
      "Developer",
      "Data & privacy",
      "Ordering engine",
    ]);
    expect(links[3]).toHaveAttribute("href", "/settings/team");
  });

  it.each(SETTINGS_SECTIONS)("gives $label a route and a heading", async ({ id, label }) => {
    renderApp(`/settings/${id}`);
    expect(await screen.findByRole("heading", { level: 2, name: label })).toBeInTheDocument();
    expect(within(await sectionNav()).getByRole("link", { name: label })).toHaveAttribute("aria-current", "page");
  });

  it("loads real content in a formerly placeholder section", async () => {
    renderApp("/settings/team");
    expect(await screen.findByText(/Roles are managed by the gateway/)).toBeInTheDocument();
  });

  it("moves between sections from the nav", async () => {
    const { router } = renderApp("/settings/team");
    await userEvent.click(within(await sectionNav()).getByRole("link", { name: "Appearance" }));
    expect(await screen.findByRole("heading", { level: 2, name: "Appearance" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/settings/appearance");
    expect(screen.getAllByRole("link", { name: "Settings" })[0]).toHaveAttribute("aria-current", "page");
  });

  it("opens the ordering engine at /settings on a wide screen", async () => {
    vi.stubGlobal("matchMedia", (query: string) => ({
      matches: query === "(min-width: 768px)",
      addEventListener: () => {},
      removeEventListener: () => {},
    }));
    const { router } = renderApp("/settings");
    expect(await screen.findByRole("heading", { level: 2, name: "Ordering engine" })).toBeInTheDocument();
    expect(router.state.location.pathname).toBe("/settings/engine");
  });

  it("says so when the section does not exist", async () => {
    renderApp("/settings/nope");
    expect(await screen.findByRole("heading", { name: "No such settings section" })).toBeInTheDocument();
  });
});
