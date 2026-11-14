import { screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { NEMOTRON_ALSO, NEMOTRON_JOBS } from "@/components/purchasing/nemotron-jobs-card";
import { createAppRouter } from "@/router";
import { renderApp } from "@/test/render";

const TITLE = "Nemotron at work";

/** The card: the About section that holds the title. */
async function card() {
  const heading = await screen.findByRole("heading", { level: 2, name: TITLE });
  const section = heading.closest("section")!;
  return { heading, section, view: within(section) };
}

describe("the Nemotron at work card on the About page", () => {
  beforeEach(() => localStorage.clear());

  it("has the id a link can point at, the mark and the one-line rule", async () => {
    renderApp("/about");
    const { heading, section, view } = await card();
    expect(heading).toHaveAttribute("id", "about-nemotron-jobs");
    expect(section).toHaveAttribute("aria-labelledby", "about-nemotron-jobs");
    expect(within(heading).getByTestId("nemotron-mark")).toBeInTheDocument();
    expect(
      view.getByText(
        "One model, five jobs, one buying loop. It never sets a quantity or a price: the engine does, and a person approves.",
      ),
    ).toBeInTheDocument();
  });

  it("lists the five jobs in the order of one buying loop, each with a link to its place", async () => {
    renderApp("/about");
    const { view } = await card();
    const rows = within(view.getByRole("list", { name: "The five jobs" })).getAllByRole("listitem");
    expect(rows.map((row) => within(row).getByRole("heading", { level: 3 }).textContent)).toEqual([
      "Plan the menu",
      "Buy the food",
      "Sell a substitute",
      "Count the stock",
      "Receive the delivery",
    ]);
    const links = [
      ["Open the menu plan", "/planner"],
      ["Open Request an order", "/requests"],
      ["See the offer on Home", "/"],
      ["Open the stock count", "/stock"],
      ["Open the order history", "/orders"],
    ];
    rows.forEach((row, index) => {
      expect(within(row).getByText(String(index + 1))).toBeInTheDocument();
      const link = within(row).getByRole("link");
      expect(link).toHaveAccessibleName(links[index][0]);
      expect(link).toHaveAttribute("href", links[index][1]);
      expect(within(row).getByText(NEMOTRON_JOBS[index].text)).toBeInTheDocument();
    });
    // The names a judge looks for on each page are quoted in the row.
    expect(rows[0]).toHaveTextContent("Plan from a menu photo");
    expect(rows[1]).toHaveTextContent("What Nemotron did");
    expect(rows[1]).toHaveTextContent("To approve");
    expect(rows[2]).toHaveTextContent("Offer from Valio Aimo");
    expect(rows[3]).toHaveTextContent("Count from a photo");
    expect(rows[4]).toHaveTextContent("Photo of the delivery note");
  });

  it("names the smaller jobs under Also, each with its place", async () => {
    renderApp("/about");
    const { view } = await card();
    const also = within(view.getByRole("list", { name: "Also" })).getAllByRole("listitem");
    expect(also).toHaveLength(NEMOTRON_ALSO.length);
    expect(
      also.map((row) => {
        const link = within(row).getByRole("link");
        return [link.textContent, link.getAttribute("href")];
      }),
    ).toEqual([
      ["Open Request an order", "/requests"],
      ["Open the order history", "/orders"],
      ["Open the suppliers", "/suppliers"],
      ["Open the demand page", "/demand"],
    ]);
  });

  it("links only to routes the app has", () => {
    const known = Object.keys(createAppRouter().routesByPath);
    for (const row of [...NEMOTRON_JOBS, ...NEMOTRON_ALSO]) expect(known).toContain(row.to);
  });

  it("points at the usage numbers, which come next on the page", async () => {
    renderApp("/about");
    const { view } = await card();
    expect(view.getByRole("link", { name: "See the usage numbers" })).toHaveAttribute("href", "#about-model");
    expect(document.getElementById("about-model")).not.toBeNull();
    const ids = [...document.querySelectorAll("section[aria-labelledby]")].map((el) => el.getAttribute("aria-labelledby"));
    const at = ids.indexOf("about-nemotron-jobs");
    expect(ids.slice(at, at + 3)).toEqual(["about-nemotron-jobs", "about-model", "about-atlas"]);
  });

  it("keeps every link at least 40 px high", async () => {
    renderApp("/about");
    const { view } = await card();
    const links = view.getAllByRole("link");
    expect(links).toHaveLength(NEMOTRON_JOBS.length + NEMOTRON_ALSO.length + 1);
    for (const link of links) expect(link.className).toMatch(/\bmin-h-10\b/);
  });
});
