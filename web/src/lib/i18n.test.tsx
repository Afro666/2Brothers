import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { MOCK_DEMO_ACCOUNTS } from "@/api/mock-auth";
import { KITCHEN_NAV, VALIO_NAV } from "@/components/purchasing/app-shell";
import { OPTIONS as THEME_OPTIONS } from "@/components/purchasing/theme-picker";
import { setAppearance, useAppearance } from "@/lib/appearance";
import { formatDate, formatEur } from "@/lib/format";
import {
  collectFinnishDictionaries,
  LanguageProvider,
  translate,
  useLanguage,
  useT,
} from "@/lib/i18n";
import { ROLE_LABELS } from "@/lib/role";
import { RULES, STEPS } from "@/pages/about";
import { KIND_LABEL } from "@/pages/home/drift";
import { WEEKDAYS } from "@/pages/settings/appearance";
import { renderApp } from "@/test/render";

function LanguageProbe() {
  const { language, setLanguage } = useLanguage();
  const t = useT();
  return (
    <>
      <output data-testid="language">{language}</output>
      <p>{t("Offer from {supplier}", { supplier: "Valio Aimo" })}</p>
      <button onClick={() => setLanguage("fi")}>Finnish</button>
    </>
  );
}

function FormatProbe() {
  const { language, setLanguage } = useLanguage();
  const appearance = useAppearance();
  return (
    <>
      <output data-testid="date" data-date-format={appearance.dateFormat}>
        {formatDate("2026-11-14")}
      </output>
      <output data-testid="money">{formatEur(1000.5)}</output>
      <button onClick={() => setLanguage(language === "en" ? "fi" : "en")}>Switch language</button>
      <button onClick={() => setAppearance({ dateFormat: "mdy", numberFormat: "space" })}>Alternate formats</button>
    </>
  );
}

function DateOnlyProbe() {
  return <output data-testid="date-only">{formatDate("2026-11-14")}</output>;
}

const TRANSLATED_FILES = [
  "components/purchasing/app-shell.tsx",
  "components/purchasing/theme-picker.tsx",
  "components/purchasing/language-picker.tsx",
  "components/purchasing/loading-state.tsx",
  "components/purchasing/empty-state.tsx",
  "components/purchasing/error-state.tsx",
  "components/purchasing/sample-data.tsx",
  "pages/home.tsx",
  "pages/home/kitchen.tsx",
  "pages/home/valio.tsx",
  "pages/home/drift.tsx",
  "pages/home/offer.tsx",
  "pages/home/tile.tsx",
  "pages/sign-in.tsx",
  "pages/settings/account.tsx",
  "pages/settings/appearance.tsx",
  "pages/about.tsx",
];

describe("language", () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.lang = "en";
    setAppearance({ dateFormat: "dmy", numberFormat: "comma" });
  });

  afterEach(() => {
    localStorage.clear();
    document.documentElement.lang = "en";
  });

  it("defaults to English and falls back to the English text", () => {
    render(
      <LanguageProvider>
        <LanguageProbe />
      </LanguageProvider>,
    );
    expect(screen.getByTestId("language")).toHaveTextContent("en");
    expect(screen.getByText("Offer from Valio Aimo")).toBeInTheDocument();
    expect(translate("fi", "This entry is missing")).toBe("This entry is missing");
  });

  it("replaces placeholders in both languages", () => {
    expect(translate("en", "Offer from {supplier}", { supplier: "Valio Aimo" })).toBe("Offer from Valio Aimo");
    expect(translate("fi", "Offer from {supplier}", { supplier: "Valio Aimo" })).toBe(
      "Tarjous: Valio Aimo",
    );
  });

  it.each(["toString", "constructor", "__proto__"])("falls back to English for %s", (text) => {
    expect(translate("fi", text)).toBe(text);
  });

  it("re-renders a date-only component when the language changes", async () => {
    const user = userEvent.setup();
    render(
      <LanguageProvider>
        <DateOnlyProbe />
        <LanguageProbe />
      </LanguageProvider>,
    );
    expect(screen.getByTestId("date-only")).toHaveTextContent("Sat 14 Nov");

    await user.click(screen.getByRole("button", { name: "Finnish" }));
    expect(screen.getByTestId("date-only")).toHaveTextContent("la 14. marrask.");
  });

  it("keeps number and date choices while translating date names", async () => {
    const user = userEvent.setup();
    render(
      <LanguageProvider>
        <FormatProbe />
      </LanguageProvider>,
    );
    expect(screen.getByTestId("date")).toHaveTextContent("Sat 14 Nov");
    expect(screen.getByTestId("money")).toHaveTextContent("€1,000.50");

    await user.click(screen.getByRole("button", { name: "Switch language" }));
    expect(screen.getByTestId("date")).toHaveTextContent("la 14. marrask.");
    expect(screen.getByTestId("money")).toHaveTextContent("€1,000.50");

    await user.click(screen.getByRole("button", { name: "Alternate formats" }));
    expect(screen.getByTestId("date")).toHaveTextContent("la, marrask. 14");
    expect(screen.getByTestId("money")).toHaveTextContent("1 000,50 €");

    await user.click(screen.getByRole("button", { name: "Switch language" }));
    expect(screen.getByTestId("date")).toHaveTextContent("Sat, Nov 14");
    expect(screen.getByTestId("money")).toHaveTextContent("1 000,50 €");
  });

  it("persists the choice and sets the document language", async () => {
    const user = userEvent.setup();
    const first = render(
      <LanguageProvider>
        <LanguageProbe />
      </LanguageProvider>,
    );
    await user.click(screen.getByRole("button", { name: "Finnish" }));
    expect(localStorage.getItem("purchasing-language")).toBe("fi");
    expect(document.documentElement).toHaveAttribute("lang", "fi");
    first.unmount();

    render(
      <LanguageProvider>
        <LanguageProbe />
      </LanguageProvider>,
    );
    expect(screen.getByTestId("language")).toHaveTextContent("fi");
    expect(document.documentElement).toHaveAttribute("lang", "fi");
  });

  it("rejects conflicting duplicate dictionary keys", () => {
    expect(() =>
      collectFinnishDictionaries({
        "a.ts": { default: { "Same text": "Hei" } },
        "b.ts": { default: { "Same text": "Moi" } },
      }),
    ).toThrow(/Conflicting Finnish translations/);
  });

  it("has a Finnish entry for every literal passed to t in translated files", () => {
    const files = import.meta.glob("../i18n/fi/*.ts", { eager: true }) as Record<
      string,
      { default: Record<string, string> }
    >;
    const dictionary = collectFinnishDictionaries(files);
    const missing: string[] = [];
    for (const file of TRANSLATED_FILES) {
      const source = readFileSync(resolve(process.cwd(), "src", file), "utf8");
      for (const match of source.matchAll(/\bt\("((?:\\.|[^"\\])*)"/g)) {
        const text = JSON.parse(`"${match[1]}"`) as string;
        if (!dictionary[text]) missing.push(`${file}: ${text}`);
      }
    }
    const dynamicTexts = [
      ...[KITCHEN_NAV, VALIO_NAV].flatMap((items) =>
        items.flatMap((item) => (item.group ? [item.label, item.group] : [item.label])),
      ),
      ...Object.values(ROLE_LABELS),
      ...STEPS.flatMap((step) => [step.title, step.text]),
      ...RULES.flatMap((rule) => [rule.title, rule.text]),
      ...Object.values(KIND_LABEL),
      ...MOCK_DEMO_ACCOUNTS.map((account) => account.label),
      ...THEME_OPTIONS.map((option) => option.label),
      ...WEEKDAYS,
    ];
    for (const text of dynamicTexts) {
      if (!Object.prototype.hasOwnProperty.call(dictionary, text)) missing.push(`dynamic: ${text}`);
    }
    expect(missing).toEqual([]);
  });

  it("switches the sidebar and Home, survives a reload, and switches back", async () => {
    const user = userEvent.setup();
    renderApp("/");
    const picker = await screen.findByRole("radiogroup", { name: "Language" });
    await user.click(within(picker).getByRole("radio", { name: "FI" }));
    expect(await screen.findByRole("link", { name: "Tilaukset" })).toBeInTheDocument();
    expect(screen.getByText("Nämä tarvitsevat sinua tänään.")).toBeInTheDocument();
    expect(await screen.findByText("Odottaa hyväksyntääsi")).toBeInTheDocument();

    cleanup();
    renderApp("/");
    const restored = await screen.findByRole("radiogroup", { name: "Kieli" });
    expect(within(restored).getByRole("radio", { name: "FI" })).toBeChecked();
    expect(await screen.findByRole("link", { name: "Tilaukset" })).toBeInTheDocument();
    expect(screen.getByText("Nämä tarvitsevat sinua tänään.")).toBeInTheDocument();
    expect(await screen.findByText("Odottaa hyväksyntääsi")).toBeInTheDocument();

    await user.click(within(restored).getByRole("radio", { name: "EN" }));
    expect(await screen.findByRole("link", { name: "Orders" })).toBeInTheDocument();
    expect(screen.getByText("What needs you today.")).toBeInTheDocument();
    expect(await screen.findByText("Waiting for your approval")).toBeInTheDocument();
  });
});
