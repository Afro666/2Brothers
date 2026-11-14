import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";

import { RecallPanel, recallSentence } from "@/components/purchasing/recall-panel";
import { LanguageProvider, translate } from "@/lib/i18n";
import { coffeeRecallAlert } from "@/mocks/coffee-recall";

const fi = (text: string, vars?: Record<string, string | number>) => translate("fi", text, vars);

const alert = coffeeRecallAlert("2026-11-14T00:30:00Z");

describe("recall sentences", () => {
  it("translates the stock and recipe lines in Finnish and keeps the list as sent", () => {
    expect(recallSentence("in stock: 3.253 KG", fi)).toBe("Varastossa: 3.253 KG");
    expect(recallSentence("in recipes: Breakfast buffet, Hospital sides, Restaurant sides", fi)).toBe(
      "Resepteissä: Breakfast buffet, Hospital sides, Restaurant sides",
    );
    expect(recallSentence("on the open purchase proposal", fi)).toBe("Avoimessa ostoehdotuksessa");
    expect(recallSentence("on the stock list: amount not counted", fi)).toBe("Varastolistalla: määrää ei ole laskettu");
  });

  it("translates the next step and keeps the lot list as sent", () => {
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
  });

  it("shows an unknown shape in the gateway's words, starting with a capital", () => {
    expect(recallSentence("in the freezer since Tuesday", fi)).toBe("In the freezer since Tuesday");
    expect(recallSentence("in stock: 3.253 KG", (text, vars) => translate("en", text, vars))).toBe("In stock: 3.253 KG");
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

  it("shows the where lines and the next step in Finnish, and English as sent in English", () => {
    const unheld = { ...alert, orderId: null, replacement: null };
    const { unmount } = render(<LanguageProvider><RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: null, unheld: [unheld] }} /></LanguageProvider>);
    expect(
      screen.getByText("Älä käytä ennen tarkistusta. Tarkista pakkauksesi: vain 23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 ja 5.9.2027 on vedetty takaisin."),
    ).toBeInTheDocument();
    unmount();

    localStorage.setItem("purchasing-language", "en");
    render(<LanguageProvider><RecallPanel status={{ kind: "ready", affecting: 0, lastCheck: null, unheld: [unheld] }} /></LanguageProvider>);
    expect(screen.getByText("In stock: 5.673 KG")).toBeInTheDocument();
    expect(screen.getByText("In recipes: breakfast_buffet")).toBeInTheDocument();
    expect(
      screen.getByText("Do not use it until checked. Check your packs: only 23.8.2027, 24.8.2027, 26.8.2027, 1.9.2027 ja 5.9.2027 are recalled."),
    ).toBeInTheDocument();
  });
});
