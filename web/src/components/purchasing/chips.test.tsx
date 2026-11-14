import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { AllergenChip } from "@/components/purchasing/chips";
import { LanguageProvider, useLanguage } from "@/lib/i18n";
import type { Allergen } from "@/types";

function Finnish() {
  const { setLanguage } = useLanguage();
  return <button onClick={() => setLanguage("fi")}>Finnish</button>;
}

/** A chip under the app's language provider, with a way to switch language as a person does. */
function renderChip(allergen: Allergen) {
  render(
    <LanguageProvider>
      <AllergenChip allergen={allergen} />
      <Finnish />
    </LanguageProvider>,
  );
}

describe("AllergenChip", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => localStorage.clear());

  it("names a member code instead of showing GO", () => {
    renderChip({ code: "GO", name: "GO", presence: "CONTAINS" });
    expect(screen.getByText("Oats")).toBeInTheDocument();
    expect(screen.queryByText("GO")).not.toBeInTheDocument();
  });

  it("uses the shared name even when the row's name is another word", () => {
    renderChip({ code: "AW", name: "Gluten", presence: "MAY_CONTAIN" });
    expect(screen.getByText("Gluten cereals")).toBeInTheDocument();
  });

  it("says an allergen the table does not know, never a bare code", () => {
    renderChip({ code: "BP", name: "Sesame seeds", presence: "CONTAINS" });
    expect(screen.getByText("Other allergen (BP)")).toBeInTheDocument();
    expect(screen.queryByText(/Sesame seeds/)).not.toBeInTheDocument();
  });

  it("names the allergens in Finnish", async () => {
    renderChip({ code: "AF", name: "Fish", presence: "CONTAINS" });
    await userEvent.setup().click(screen.getByRole("button", { name: "Finnish" }));
    expect(screen.getByText("Kala")).toBeInTheDocument();
    expect(screen.getByText("Sisältää")).toBeInTheDocument();
  });
});
