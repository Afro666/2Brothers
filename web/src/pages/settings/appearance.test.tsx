import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { getAppearance, loadAppearance } from "@/lib/appearance";
import { formatDate, formatDateTime, formatEur, formatStock } from "@/lib/format";
import { renderApp } from "@/test/render";

const html = document.documentElement;

afterEach(() => {
  vi.restoreAllMocks();
  localStorage.clear();
  loadAppearance();
});

/** The section's own controls: the sidebar has a theme picker too. */
async function appearance() {
  renderApp("/settings/appearance");
  const heading = await screen.findByRole("heading", { level: 2, name: "Appearance" });
  return within(heading.closest("section")!);
}

describe("appearance settings", () => {
  it("starts on the defaults", async () => {
    const section = await appearance();
    expect(section.getByRole("radio", { name: "Herb green" })).toBeChecked();
    expect(section.getByRole("radio", { name: "Comfortable" })).toBeChecked();
    expect(section.getByRole("radio", { name: "1,000.50" })).toBeChecked();
    expect(section.getByRole("radio", { name: "14 Nov" })).toBeChecked();
    expect(section.getByRole("checkbox", { name: "Week starts on Monday" })).toBeChecked();
    expect(section.getByRole("radiogroup", { name: "Theme" })).toBeInTheDocument();
    expect(section.getByText(/More languages will come here/)).toBeInTheDocument();
    expect(html).toHaveAttribute("data-accent", "herb");
    expect(html).toHaveAttribute("data-density", "comfortable");
  });

  it("an accent applies at once and survives a reload", async () => {
    const section = await appearance();
    await userEvent.click(section.getByRole("radio", { name: "Blue" }));
    expect(html).toHaveAttribute("data-accent", "blue");
    expect(html.style.getPropertyValue("--accent-hue")).toBe("255");

    // A reload: the page starts again from what is stored.
    html.removeAttribute("data-accent");
    loadAppearance();
    expect(html).toHaveAttribute("data-accent", "blue");
    expect(getAppearance().accent).toBe("blue");
  });

  it("density, number format, date format and week start apply at once", async () => {
    const section = await appearance();
    expect(section.getByText("€1,000.50")).toBeInTheDocument();
    expect(section.getByText("Sat 14 Nov")).toBeInTheDocument();
    expect(section.getByText("Mon Tue Wed Thu Fri Sat Sun")).toBeInTheDocument();

    await userEvent.click(section.getByRole("radio", { name: "Compact" }));
    await userEvent.click(section.getByRole("radio", { name: "1 000,50" }));
    await userEvent.click(section.getByRole("radio", { name: "14.11." }));
    await userEvent.click(section.getByRole("checkbox", { name: "Week starts on Monday" }));

    expect(html).toHaveAttribute("data-density", "compact");
    // fi-FI groups with a no-break space; getByText compares against the text with plain spaces.
    expect(section.getByText("1 000,50 €")).toBeInTheDocument();
    expect(section.getByText("Sat 14.11.")).toBeInTheDocument();
    expect(section.getByText("Sun Mon Tue Wed Thu Fri Sat")).toBeInTheDocument();
    expect(formatEur(1947.5)).toBe("1\u00a0947,50\u00a0€");
    expect(formatStock(1200, "KI")).toBe("1\u00a0200 KI");
    expect(formatDateTime("2026-11-14T10:30:00+02:00")).toBe("Sat 14.11., 10:30");

    await userEvent.click(section.getByRole("radio", { name: "Nov 14" }));
    expect(formatDate("2026-11-14")).toBe("Sat, Nov 14");
    expect(JSON.parse(localStorage.getItem("purchasing-appearance")!)).toEqual({
      accent: "herb",
      density: "compact",
      numberFormat: "space",
      dateFormat: "mdy",
      weekStartsMonday: false,
    });
  });

  it("ignores stored values that are not options", () => {
    localStorage.setItem("purchasing-appearance", JSON.stringify({ accent: "pink", density: "compact" }));
    loadAppearance();
    expect(getAppearance()).toMatchObject({ accent: "herb", density: "compact", numberFormat: "comma" });

    localStorage.setItem("purchasing-appearance", "not json");
    loadAppearance();
    expect(getAppearance().density).toBe("comfortable");
  });

  it("works when storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    loadAppearance();
    const section = await appearance();
    await userEvent.click(section.getByRole("radio", { name: "Teal" }));
    expect(html).toHaveAttribute("data-accent", "teal");
  });
});
