import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { renderApp } from "@/test/render";

describe("AboutPage", () => {
  beforeEach(() => localStorage.clear());

  it("shows the companies whose services the product uses", async () => {
    renderApp("/about");

    expect(await screen.findByRole("heading", { name: "Built with" })).toBeInTheDocument();
    const section = screen.getByRole("heading", { name: "Built with" }).closest("section")!;
    for (const [alt, file] of [
      ["MongoDB Atlas logo", "mongodb.svg"],
      ["NVIDIA Nemotron 3.5 Super VL logo", "nvidia.svg"],
      ["Context.dev logo", "contextdev.png"],
      ["OpenAI Codex logo", "openai.svg"],
      ["Verda logo", "verda.svg"],
    ]) {
      const logo = within(section).getByAltText(alt);
      expect(logo).toHaveAttribute("src", expect.stringMatching(new RegExp(`${file}$`)));
      expect(logo).toHaveAttribute("loading", "lazy");
    }
    for (const title of ["MongoDB Atlas: the only database", "NVIDIA Nemotron 3.5 Super VL: the Buyer agent"]) {
      expect(within(section).getByRole("heading", { name: title })).toBeInTheDocument();
    }
    // The live counts belong to the Atlas card below: this section links to it and repeats no number.
    expect(within(section).getByRole("link", { name: "See the live Atlas numbers" })).toHaveAttribute("href", "#about-atlas");
    expect(section).not.toHaveTextContent("17,546");
    for (const [name, href] of [
      ["Search the catalog", "/catalog"],
      ["Open the inbox", "/approvals"],
      ["See it on Home", "/"],
      ["Run the tamper check", "/trust"],
      ["Request an order", "/requests"],
      ["Count from a photo", "/stock"],
      ["The offer on Home", "/"],
      ["See a proposal", "/approvals"],
      ["See the recall box", "/approvals"],
    ]) {
      expect(within(section).getByRole("link", { name })).toHaveAttribute("href", href);
    }
    // Named with one line each, and no numbers for them (#1388).
    const also = within(section).getByRole("list", { name: "Also used" });
    expect(within(also).getAllByRole("listitem")).toHaveLength(3);
    expect(within(also).getByText("OpenAI Codex wrote part of the Buyer agent and its tools.")).toBeInTheDocument();
    expect(within(also).getByText("Verda runs the model's endpoint and this site.")).toBeInTheDocument();
  });

  it("explains the flow, the two sides and the trust rules", async () => {
    renderApp("/about");
    expect(await screen.findByRole("heading", { level: 1, name: "About Kitchen Buyer" })).toBeInTheDocument();
    const steps = screen.getAllByRole("list").find((list) => list.tagName === "OL")!;
    expect(
      within(steps)
        .getAllByRole("heading", { level: 3 })
        .map((heading) => heading.textContent),
    ).toEqual(["Request", "Lookup", "Order at a fixed price", "Approval"]);
    for (const name of [
      "The kitchen",
      "Valio",
      "A person approves every order",
      "Unknown is never treated as zero or safe",
      "Everything is audited",
      "Forecasts are shared only with consent",
    ]) {
      expect(screen.getByRole("heading", { level: 3, name })).toBeInTheDocument();
    }
  });

  it.each(["Kitchen", "Valio planner"])("is linked from the nav when viewing as %s", async (role) => {
    const user = userEvent.setup();
    renderApp("/");
    const picker = (await screen.findAllByRole("radiogroup", { name: "Your role" }))[0]!;
    await user.click(within(picker).getByRole("radio", { name: role }));
    await user.click(within(screen.getByRole("navigation", { name: "Main" })).getByRole("link", { name: "About" }));
    expect(await screen.findByRole("heading", { level: 1, name: "About Kitchen Buyer" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "About" })).toHaveAttribute("aria-current", "page");
  });
});
