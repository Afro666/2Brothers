import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { products } from "@/mocks/milk-case";

import { ProductCard } from "./product-card";

describe("ProductCard catalog facts", () => {
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
});
