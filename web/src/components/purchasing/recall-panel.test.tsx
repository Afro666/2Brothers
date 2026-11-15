import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { RecallPanel, recallSentence, type RecallStatus } from "@/components/purchasing/recall-panel";
import { LanguageProvider, translate, updateLanguage } from "@/lib/i18n";
import { coffeeRecallAlert } from "@/mocks/coffee-recall";
import type { RecallAlert, RecallCheck } from "@/types";

const fi = (text: string, vars?: Record<string, string | number>) => translate("fi", text, vars);

const alert = coffeeRecallAlert("2026-11-14T00:30:00Z");

describe("recall sentences", () => {
  afterEach(() => updateLanguage("en", false));

  it("translates the stock and recipe lines in Finnish and keeps the list as sent", () => {
    updateLanguage("fi", false);
    expect(recallSentence("in stock: 3.253 KG", fi)).toBe("Varastossa: 3,3 kg");
    expect(recallSentence("in recipes: Breakfast buffet, Hospital sides, Restaurant sides", fi)).toBe(
      "Resepteissä: Breakfast buffet, Hospital sides, Restaurant sides",
    );
    expect(recallSentence("on the open purchase proposal", fi)).toBe("Avoimessa ostoehdotuksessa");
    expect(recallSentence("on the stock list: amount not counted", fi)).toBe("Varastolistalla: määrää ei ole laskettu");
  });

  it("translates the next step and localizes the final lot conjunction", () => {
    expect(
      recallSentence(
        "Do not use it until checked. Check your packs: only 23.8.2027, 24.8.2027 ja 5.9.2027 are recalled.",
        fi,
      ),
    ).toBe("Älä käytä ennen tarkistusta. Tarkista pakkauksesi: vain 23.8.2027, 24.8.2027 ja 5.9.2027 on vedetty takaisin.");
    expect(recallSentence("Stop using it now. Check your packs.", fi)).toBe(
      "Lopeta käyttö heti. Tarkista pakkauksesi.",
    );
    expect(recallSentence("A person checks whether this notice is about your product.", fi)).toBe(
      "Ihminen tarkistaa, koskeeko ilmoitus tuotettasi.",
    );
    expect(
      recallSentence(
        "Do not use it until checked. Check your packs: only 1.9.2027 ja 5.9.2027 are recalled.",
        (text, vars) => translate("en", text, vars),
      ),
    ).toBe("Do not use it until checked. Check your packs: only 1.9.2027 and 5.9.2027 are recalled.");
  });

  it("shows an unknown shape as sent, in both languages", () => {
    expect(recallSentence("in the freezer since Tuesday", fi)).toBe("in the freezer since Tuesday");
    expect(recallSentence("in stock: 3.253 KG", (text, vars) => translate("en", text, vars))).toBe("In stock: 3.3 kg");
  });
});

describe("RecallPanel in Finnish", () => {
  beforeEach(() => {
    localStorage.clear();
    localStorage.setItem("purchasing-language", "fi");
  });

  afterEach(() => {
    localStorage.setItem("purchasing-language", "en");
    localStorage.clear();
  });

  it("shows the where lines and the next step in Finnish, and translates the date conjunction in English", () => {
    const unheld = { ...alert, orderId: null, replacement: null };
    const { unmount } = render(<LanguageProvider><RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: null, unheld: [unheld] }} /></LanguageProvider>);
    expect(
      screen.getByText("Älä käytä ennen tarkistusta. Tarkista pakkauksesi: vain 23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 ja 5.9.2027 on vedetty takaisin."),
    ).toBeInTheDocument();
    unmount();

    localStorage.setItem("purchasing-language", "en");
    render(<LanguageProvider><RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: null, unheld: [unheld] }} /></LanguageProvider>);
    expect(screen.getByText("In stock: 5.7 kg")).toBeInTheDocument();
    expect(screen.getByText("In recipes: breakfast_buffet")).toBeInTheDocument();
    expect(
      screen.getByText("Do not use it until checked. Check your packs: only 23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 and 5.9.2027 are recalled."),
    ).toBeInTheDocument();
  });

  it("writes the folded row in Finnish", () => {
    const unheld = { ...alert, orderId: null, replacement: null };
    render(<LanguageProvider><RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: null, unheld: [unheld] }} onCheck={async () => undefined} /></LanguageProvider>);
    expect(screen.getByRole("status")).toHaveTextContent(
      "1 takaisinveto: Kulta Katriina Traditional fine ground filter coffee RAC 5x1kg on varastossasi (5,7 kg).",
    );
    expect(screen.getByTestId("recall-next")).toHaveTextContent(/^Älä käytä ennen tarkistusta\.$/);
    expect(screen.getByRole("button", { name: "Tiedot" })).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByRole("button", { name: "Tarkista takaisinvedot nyt" })).toBeInTheDocument();
  });
});

describe("RecallPanel, folded and unfolded", () => {
  const unheld: RecallAlert = { ...alert, orderId: null, replacement: null, where: alert.where.slice(0, 2) };
  const check: RecallCheck = {
    checkedAt: "2026-11-14T17:37:00Z",
    fetchedAt: "2026-11-14T17:37:00Z",
    source: "live",
    liveError: null,
    via: "Context.dev /v1/web/scrape (json)",
    noticesScanned: 38,
    noticesListed: 102,
    noticesUnread: null,
    scannedSince: "2026-03-02",
    detailsFetchedAt: null,
    checkedBy: null,
  };
  const ready = (alerts: RecallAlert[], affecting = 0): RecallStatus => ({
    kind: "ready",
    affecting,
    lastCheck: check,
    unheld: alerts,
  });
  const toggle = () => screen.getByRole("button", { name: "Details" });
  const details = () => document.getElementById(toggle().getAttribute("aria-controls")!)!;

  beforeEach(() => {
    localStorage.clear();
    updateLanguage("en", false);
  });

  it("is one folded row by default: what, where, what to do, and the two controls", () => {
    render(<RecallPanel status={ready([unheld])} onCheck={async () => undefined} />);
    const panel = screen.getByRole("region", { name: "Food recalls" });
    expect(within(panel).getByRole("status")).toHaveTextContent(
      "1 recall: Kulta Katriina Traditional fine ground filter coffee RAC 5x1kg is in your stock (5.7 kg).",
    );
    expect(within(panel).getByTestId("recall-next")).toHaveTextContent(/^Do not use it until checked\.$/);
    expect(within(panel).getByTestId("recall-next")).toBeVisible();
    // #1978: on a phone the product name wraps; it is cut to one line only from the `sm` width up.
    const name = within(panel).getByTitle("Kulta Katriina Traditional fine ground filter coffee RAC 5x1kg");
    expect(name.className.split(" ")).toContain("sm:truncate");
    expect(name.className.split(" ")).not.toContain("truncate");
    expect(within(panel).getByRole("status").className.split(" ")).toContain("max-sm:block");
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(details()).not.toBeVisible();
    expect(within(panel).queryByRole("list")).not.toBeInTheDocument();
    expect(within(panel).queryByRole("link")).not.toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Check recalls now" })).toBeEnabled();
    // The warning colour is an accent, not a full red block.
    expect(panel).toHaveClass("border-l-danger");
    expect(panel).not.toHaveClass("bg-danger-surface");
  });

  it("unfolds to everything the box showed before, and folds again", async () => {
    const user = userEvent.setup();
    render(<RecallPanel status={ready([unheld])} onCheck={async () => undefined} />);
    await user.click(toggle());
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    const box = details();
    expect(box).toBeVisible();
    expect(within(box).getByText("1 recall matches a product in your kitchen")).toBeVisible();
    expect(within(box).getByText(/Checked 38 Ruokavirasto notices, .*Scraped live: 102 notices on the list\./)).toBeVisible();
    const item = within(within(box).getByRole("list", { name: "Recalled products in your kitchen" })).getByRole("listitem");
    expect(item).toHaveTextContent("Kulta Katriina Traditional fine ground filter coffee RAC 5x1kg is recalled.");
    expect(within(item).getByRole("link", { name: /Suodatinkahvissa vierasesineriski/ })).toHaveAttribute("href", alert.recall.url);
    expect(within(item).getByText("In stock: 5.7 kg")).toBeVisible();
    expect(within(item).getByText("In recipes: breakfast_buffet")).toBeVisible();
    expect(within(item).getByText("No open order holds it. New orders leave it out.")).toBeVisible();
    expect(
      within(item).getByText("Do not use it until checked. Check your packs: only 23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 and 5.9.2027 are recalled."),
    ).toBeVisible();
    expect(within(box).getByText(/Powered by Context\.dev/)).toHaveTextContent("Powered by Context.dev /v1/web/scrape");

    await user.click(toggle());
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    expect(details()).not.toBeVisible();
  });

  it("works from the keyboard: the toggle is a real button before the check button", async () => {
    const user = userEvent.setup();
    render(<RecallPanel status={ready([unheld])} onCheck={async () => undefined} />);
    await user.tab();
    expect(toggle()).toHaveFocus();
    expect(toggle().tagName).toBe("BUTTON");
    await user.keyboard("{Enter}");
    expect(toggle()).toHaveAttribute("aria-expanded", "true");
    await user.keyboard(" ");
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
    await user.tab();
    expect(screen.getByRole("button", { name: "Check recalls now" })).toHaveFocus();
  });

  it("keeps several recalls on one row: the count and the names", async () => {
    const user = userEvent.setup();
    const three = [
      unheld,
      { ...unheld, eventId: "recall-2", productId: "475842", productName: "Löfbergs Crescendo Ground Coffee" },
      { ...unheld, eventId: "recall-3", productId: "400100", productName: null },
    ];
    render(<RecallPanel status={ready(three)} onCheck={async () => undefined} />);
    expect(screen.getByRole("status")).toHaveTextContent(/^3 recalls match products in your kitchen$/);
    expect(screen.getByTestId("recall-next")).toHaveTextContent(
      "Kulta Katriina Traditional fine ground filter coffee RAC 5x1kg, Löfbergs Crescendo Ground Coffee, 400100",
    );
    expect(screen.queryByRole("list")).not.toBeInTheDocument();
    await user.click(toggle());
    expect(within(screen.getByRole("list", { name: "Recalled products in your kitchen" })).getAllByRole("listitem")).toHaveLength(3);
    // The row already says it: no second copy of the headline in the details.
    expect(screen.getAllByText("3 recalls match products in your kitchen")).toHaveLength(1);
  });

  it("says where the product is when it is not counted in stock", () => {
    const { rerender } = render(<RecallPanel status={ready([{ ...unheld, where: ["in recipes: breakfast_buffet"] }])} />);
    expect(screen.getByRole("status")).toHaveTextContent(/^1 recall: Kulta Katriina .* RAC 5x1kg is in your recipes\.$/);
    rerender(<RecallPanel status={ready([{ ...unheld, where: ["on the stock list: amount not counted"] }])} />);
    expect(screen.getByRole("status")).toHaveTextContent(/^1 recall: Kulta Katriina .* RAC 5x1kg is on your stock list\.$/);
    rerender(<RecallPanel status={ready([{ ...unheld, where: [], nextStep: "Stop using it now. Check your packs." }])} />);
    expect(screen.getByRole("status")).toHaveTextContent(/^1 recall: Kulta Katriina .* RAC 5x1kg is recalled\.$/);
    expect(screen.getByTestId("recall-next")).toHaveTextContent(/^Stop using it now\.$/);
    rerender(<RecallPanel status={ready([{ ...unheld, where: [], nextStep: "Call the supplier." }])} />);
    expect(screen.queryByTestId("recall-next")).not.toBeInTheDocument();
  });

  it("folds a review match with the warning accent, never the red one", () => {
    const review: RecallAlert = {
      ...unheld,
      match: "review",
      lineStatus: "WARNING",
      productName: null,
      nextStep: "A person checks whether this notice is about your product.",
    };
    render(<RecallPanel status={ready([review])} />);
    const panel = screen.getByRole("region", { name: "Food recalls" });
    expect(within(panel).getByRole("status")).toHaveTextContent(/^1 recall notice may be about 461332\.$/);
    expect(within(panel).getByTestId("recall-next")).toHaveTextContent("A person checks whether this notice is about your product.");
    expect(panel).toHaveClass("border-l-warning");
    expect(panel).not.toHaveClass("border-l-danger");
  });

  it("folds a recall on an open order too, and names nothing the order card already shows", async () => {
    const user = userEvent.setup();
    render(<RecallPanel status={ready([], 1)} onCheck={async () => undefined} />);
    const panel = screen.getByRole("region", { name: "Food recalls" });
    expect(within(panel).getByRole("status")).toHaveTextContent(/^1 recall affects your open order$/);
    expect(panel).toHaveClass("border-l-danger");
    expect(within(panel).queryByTestId("recall-next")).not.toBeInTheDocument();
    await user.click(toggle());
    expect(within(details()).getByText(/Checked 38 Ruokavirasto notices/)).toBeVisible();
    expect(within(details()).queryByRole("list")).not.toBeInTheDocument();
  });

  it("shows a failed check on the folded row", async () => {
    const user = userEvent.setup();
    render(<RecallPanel status={ready([unheld])} onCheck={async () => { throw new Error("gateway down"); }} />);
    await user.click(screen.getByRole("button", { name: "Check recalls now" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Recall check failed: gateway down. Recalls are unknown.");
    expect(screen.getByRole("alert")).toBeVisible();
    expect(toggle()).toHaveAttribute("aria-expanded", "false");
  });

  it("keeps the quiet states as they were: no fold, no toggle", () => {
    const { rerender } = render(<RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: check }} onCheck={async () => undefined} />);
    const panel = screen.getByRole("region", { name: "Food recalls" });
    expect(panel).toHaveClass("bg-success-surface");
    expect(screen.getByRole("status")).toHaveTextContent("No recall matches your open orders.");
    expect(screen.getByText(/Checked 38 Ruokavirasto notices/)).toBeVisible();
    expect(screen.getByText(/Powered by Context\.dev/)).toBeVisible();
    expect(screen.queryByRole("button", { name: "Details" })).not.toBeInTheDocument();
    rerender(<RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: null }} onCheck={async () => undefined} />);
    expect(screen.getByRole("status")).toHaveTextContent("Recalls not checked yet.");
    expect(screen.queryByRole("button", { name: "Details" })).not.toBeInTheDocument();
  });
});
