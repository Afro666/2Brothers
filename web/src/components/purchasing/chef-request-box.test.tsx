import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChefRequestBox } from "@/components/purchasing/chef-request-box";
import { LanguageProvider } from "@/lib/i18n";

function renderBox(onSubmit = vi.fn()) {
  render(
    <LanguageProvider>
      <ChefRequestBox initial={{ text: "old text" }} onSubmit={onSubmit} />
    </LanguageProvider>,
  );
  return onSubmit;
}

describe("ChefRequestBox examples", () => {
  it("fills the box with a chip and moves focus to it, without submitting", async () => {
    const user = userEvent.setup();
    const onSubmit = renderBox();
    const box = screen.getByLabelText("What do you need?");
    const group = screen.getByRole("group", { name: "Examples" });

    expect(group.querySelectorAll("button")).toHaveLength(3);
    // A thumb hits a chip on a phone: each one is at least 44 px high.
    for (const chip of group.querySelectorAll("button")) expect(chip).toHaveClass("min-h-11");
    await user.click(screen.getByRole("button", { name: "400 pcs single-serve fruit yoghurt for Friday" }));

    expect(box).toHaveValue("400 pcs single-serve fruit yoghurt for Friday");
    expect(box).toHaveFocus();
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("in Finnish the box gets the Finnish text the chip shows", async () => {
    localStorage.setItem("purchasing-language", "fi");
    try {
      const user = userEvent.setup();
      renderBox();
      await user.click(screen.getByRole("button", { name: "100 litraa kermaa torstaiksi" }));
      expect(screen.getByRole("textbox", { name: /./ })).toHaveValue("100 litraa kermaa torstaiksi");
    } finally {
      localStorage.removeItem("purchasing-language");
    }
  });
});
