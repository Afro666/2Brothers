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
    await user.click(screen.getByRole("button", { name: "400 pcs single-serve fruit yoghurt for Friday" }));

    expect(box).toHaveValue("400 pcs single-serve fruit yoghurt for Friday");
    expect(box).toHaveFocus();
    expect(onSubmit).not.toHaveBeenCalled();
  });
});
