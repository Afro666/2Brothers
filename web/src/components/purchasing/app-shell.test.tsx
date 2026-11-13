import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it } from "vitest";

import { renderApp } from "@/test/render";

afterEach(() => {
  localStorage.clear();
  document.documentElement.removeAttribute("data-theme");
});

describe("AppShell theme choice", () => {
  it("is in the sidebar and in the phone drawer, and both show the same choice", async () => {
    renderApp("/");
    const sidebar = await screen.findByRole("radiogroup", { name: "Theme" });
    await userEvent.click(within(sidebar).getByRole("radio", { name: "Dark" }));
    expect(document.documentElement).toHaveAttribute("data-theme", "dark");

    await userEvent.click(screen.getByRole("button", { name: "Open menu" }));
    const drawer = within(await screen.findByRole("dialog")).getByRole("radiogroup", { name: "Theme" });
    expect(within(drawer).getByRole("radio", { name: "Dark" })).toBeChecked();
  });
});
