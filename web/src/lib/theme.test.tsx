import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ThemePicker } from "@/components/purchasing/theme-picker";
import { ThemeProvider, useTheme } from "@/lib/theme";

import indexHtml from "../../index.html?raw";

const html = document.documentElement;

/** A `matchMedia` whose answer a test can flip, as when the device switches scheme. */
function stubDevice(dark: boolean) {
  const listeners = new Set<() => void>();
  const query = {
    matches: dark,
    addEventListener: (_type: string, listener: () => void) => listeners.add(listener),
    removeEventListener: (_type: string, listener: () => void) => listeners.delete(listener),
  };
  vi.stubGlobal("matchMedia", () => query);
  return {
    set(next: boolean) {
      query.matches = next;
      act(() => listeners.forEach((listener) => listener()));
    },
  };
}

function Resolved() {
  return <output>{useTheme().resolved}</output>;
}

function renderPicker() {
  render(
    <ThemeProvider>
      <ThemePicker />
      <Resolved />
    </ThemeProvider>,
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  localStorage.clear();
  html.removeAttribute("data-theme");
  document.querySelector('meta[name="theme-color"]')?.remove();
});

describe("theme", () => {
  it("starts on System, which is light where there is no matchMedia", () => {
    renderPicker();
    expect(screen.getByRole("radiogroup", { name: "Theme" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "System" })).toBeChecked();
    expect(screen.getByRole("radio", { name: "Dark" })).not.toBeChecked();
    expect(html).toHaveAttribute("data-theme", "light");
  });

  it("choosing Dark sets data-theme, the browser bar colour and the stored choice", async () => {
    const meta = document.createElement("meta");
    meta.name = "theme-color";
    document.head.append(meta);
    renderPicker();
    expect(meta).toHaveAttribute("content", "#F4F1E9");

    await userEvent.click(screen.getByRole("radio", { name: "Dark" }));

    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();
    expect(html).toHaveAttribute("data-theme", "dark");
    expect(meta).toHaveAttribute("content", "#151410");
    expect(localStorage.getItem("purchasing-theme")).toBe("dark");
    expect(screen.getByRole("status")).toHaveTextContent("dark");
  });

  it("arrow keys move between the options", async () => {
    renderPicker();
    await userEvent.tab();
    expect(screen.getByRole("radio", { name: "System" })).toHaveFocus();
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();
    expect(html).toHaveAttribute("data-theme", "dark");
  });

  it("System follows the device, also when it changes", async () => {
    const device = stubDevice(true);
    localStorage.setItem("purchasing-theme", "light");
    renderPicker();
    expect(html).toHaveAttribute("data-theme", "light");

    await userEvent.click(screen.getByRole("radio", { name: "System" }));
    expect(html).toHaveAttribute("data-theme", "dark");
    expect(localStorage.getItem("purchasing-theme")).toBe("system");

    device.set(false);
    expect(html).toHaveAttribute("data-theme", "light");
  });

  it("a fixed choice ignores the device", () => {
    const device = stubDevice(false);
    localStorage.setItem("purchasing-theme", "light");
    renderPicker();
    device.set(true);
    expect(html).toHaveAttribute("data-theme", "light");
  });

  it("applies a stored choice on mount", () => {
    localStorage.setItem("purchasing-theme", "dark");
    renderPicker();
    expect(screen.getByRole("radio", { name: "Dark" })).toBeChecked();
    expect(html).toHaveAttribute("data-theme", "dark");
  });

  it("works when storage is blocked", async () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    renderPicker();
    expect(screen.getByRole("radio", { name: "System" })).toBeChecked();

    await userEvent.click(screen.getByRole("radio", { name: "Dark" }));
    expect(html).toHaveAttribute("data-theme", "dark");
  });
});

describe("the inline script in index.html", () => {
  const script = /<script>([\s\S]*?)<\/script>/.exec(indexHtml)?.[1] ?? "";
  const run = () => new Function(script)();

  it("applies the stored choice before the app loads", () => {
    localStorage.setItem("purchasing-theme", "dark");
    run();
    expect(html).toHaveAttribute("data-theme", "dark");
  });

  it("follows the device when nothing is stored or storage is blocked", () => {
    stubDevice(true);
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    run();
    expect(html).toHaveAttribute("data-theme", "dark");
  });
});
