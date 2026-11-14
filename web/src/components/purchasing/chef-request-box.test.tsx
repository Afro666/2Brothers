import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ChefRequestBox } from "@/components/purchasing/chef-request-box";
import { LanguageProvider, updateLanguage } from "@/lib/i18n";

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
    // The language store is module state, not only storage: set it the way the app does.
    localStorage.setItem("purchasing-language", "fi");
    act(() => updateLanguage("fi"));
    try {
      const user = userEvent.setup();
      renderBox();
      await user.click(screen.getByRole("button", { name: "100 litraa kermaa torstaiksi" }));
      expect(screen.getByRole("textbox", { name: /./ })).toHaveValue("100 litraa kermaa torstaiksi");
    } finally {
      localStorage.removeItem("purchasing-language");
      act(() => updateLanguage("en"));
    }
  });

  it("shows an instruction, not a filled-in request, in the empty box", () => {
    render(
      <LanguageProvider>
        <ChefRequestBox onSubmit={vi.fn()} />
      </LanguageProvider>,
    );
    const box = screen.getByLabelText("What do you need?");
    expect(box).toHaveValue("");
    expect(box).toHaveAttribute("placeholder", "Type what you need, or pick an example below");
    expect(screen.getByRole("button", { name: "Ask the agent" })).toBeDisabled();
  });

  it("a chip moves Needed by to the weekday it names, so one press can send", async () => {
    vi.useFakeTimers({ toFake: ["Date"], now: new Date("2026-11-14T22:30:00Z") });
    try {
      const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
      const onSubmit = renderBox();
      // Midnight in Helsinki is already Sunday 15 Nov; the chip says Monday.
      await act(async () => {
        await user.click(screen.getByRole("button", { name: "1,000 L lactose-free milk by Monday" }));
      });
      expect(screen.getByLabelText("Needed by")).toHaveValue("2026-11-16");
      // The day in words sits under the native field, whatever format the browser shows.
      expect(screen.getByText("Mon 16 Nov")).toBeInTheDocument();
      await act(async () => {
        await user.click(screen.getByRole("button", { name: "Ask the agent" }));
      });
      expect(onSubmit).toHaveBeenCalledWith({
        text: "1,000 L lactose-free milk by Monday",
        covers: null,
        deliveryDate: "2026-11-16",
      });
    } finally {
      vi.useRealTimers();
    }
  });
});
