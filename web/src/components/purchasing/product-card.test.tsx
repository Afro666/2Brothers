import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { updateLanguage } from "@/lib/i18n";
import { products } from "@/mocks/milk-case";

import { ProductCard } from "./product-card";

describe("ProductCard catalog facts", () => {
  afterEach(() => updateLanguage("en", false));

  it("shows the sales-unit price before VAT, or price unknown", () => {
    const { rerender } = render(<ProductCard product={{ ...products.arlaUht1l, priceExVat: 12.5 }} />);
    expect(screen.getByText("€12.50 per ST ex VAT")).toBeInTheDocument();

    rerender(<ProductCard product={{ ...products.arlaUht1l, priceExVat: null }} />);
    expect(screen.getByText("price unknown")).toBeInTheDocument();

    // A supplier's product: the search answer has no price, the offer has it.
    rerender(<ProductCard product={{ ...products.arlaUht1l, priceExVat: undefined }} />);
    expect(screen.getByText("Live price and stock come with the offer")).toBeInTheDocument();
    expect(screen.queryByText("price unknown")).not.toBeInTheDocument();
  });

  it("uses a named allergen and explains an unnamed code", () => {
    render(
      <ProductCard
        product={{
          ...products.arlaUht1l,
          allergens: [
            { code: "GB", name: "Barley", presence: "CONTAINS" },
            { code: "XX", name: "XX", presence: "CONTAINS" },
          ],
        }}
      />,
    );
    expect(screen.getByText("Barley")).toBeInTheDocument();
    expect(screen.getByText("Other allergen (XX)")).toBeInTheDocument();
  });

  it("omits unknown delivery reliability but keeps a known value", () => {
    const { rerender } = render(<ProductCard product={{ ...products.arlaUht1l, deliveryReliability: null }} />);
    expect(screen.queryByText("Delivery reliability")).not.toBeInTheDocument();

    rerender(<ProductCard product={products.arlaUht1l} />);
    expect(screen.getByText("Delivery reliability")).toBeInTheDocument();
    expect(screen.getByText("97 %")).toBeInTheDocument();
  });

  it("leads with the Finnish name and translates allergen and temperature labels", () => {
    updateLanguage("fi", false);
    render(
      <ProductCard
        product={{
          ...products.arlaUht1l,
          allergens: [{ code: "AE", name: "Eggs", presence: "MAY_CONTAIN" }],
          temperature: { code: 2, label: "Chilled, +2 to +6 °C" },
        }}
      />,
    );
    expect(screen.getByRole("link", { name: products.arlaUht1l.names.fi })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: products.arlaUht1l.names.en })).not.toBeInTheDocument();
    expect(screen.getByText("Kananmunat")).toBeInTheDocument();
    expect(screen.getByText("Jäähdytetty, +2–+6 °C")).toBeInTheDocument();
    expect(screen.queryByText(/Chilled/)).not.toBeInTheDocument();
  });

  it("falls back to the English name for an empty Finnish name, and translates an unknown temperature", () => {
    updateLanguage("fi", false);
    render(<ProductCard product={{ ...products.arlaUht1l, names: { ...products.arlaUht1l.names, fi: "" }, temperature: null }} />);
    expect(screen.getByRole("link", { name: products.arlaUht1l.names.en })).toBeInTheDocument();
    expect(screen.queryByText("unknown")).not.toBeInTheDocument();
  });
});
