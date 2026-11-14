import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ApiProvider } from "@/api";
import { createMockApi } from "@/api/mock";
import type { Api, BrandLogo } from "@/api/types";
import { Beet, Butter, Cucumber, Mushroom, Onion, Pepper, Potato, Tomato } from "@/lib/product-icons";

import { ProductThumb } from "./product-thumb";

const URL = "https://media.brand.dev/valio.png";

function logo(brand: string, found: boolean): BrandLogo {
  return found
    ? { brand, status: "found", logoUrl: URL, background: "own", domain: "valio.fi", checkedAt: "2026-11-14T12:00:00+00:00" }
    : { brand, status: "none", logoUrl: null, background: null, domain: null, checkedAt: null };
}

function withLogos(list: Api["listBrandLogos"]): Api {
  return { ...createMockApi(), listBrandLogos: list };
}

describe("ProductThumb kind tile", () => {
  it("draws a line icon on a tinted tile, not an emoji", () => {
    const { container } = render(<ProductThumb en="Valio milk 1 l" size="sm" />);
    const tile = container.querySelector("[data-kind]");
    expect(tile).toHaveAttribute("data-kind", "milk and cream");
    expect(tile).toHaveAttribute("aria-hidden");
    expect(tile?.querySelector("svg")).not.toBeNull();
    expect(tile?.className).toMatch(/bg-sky-100/);
    expect(tile?.textContent).toBe("");
  });

  it("falls back to a package icon for an unknown name", () => {
    const { container } = render(<ProductThumb en="RAPID SUPREME S50 XYZ" />);
    const tile = container.querySelector("[data-kind]");
    expect(tile).toHaveAttribute("data-kind", "product");
    expect(tile?.querySelector("svg")).not.toBeNull();
  });

  it("keeps a new pictogram decorative at every tile size", () => {
    const sizes = [["sm", "size-8", "size-4"], ["md", "size-11", "size-6"], ["lg", "size-14", "size-7"]] as const;
    for (const [size, tileSize, iconSize] of sizes) {
      const { container, unmount } = render(<ProductThumb en="Butter" size={size} />);
      const tile = container.querySelector("[data-kind]");
      const icon = tile?.querySelector(":scope > svg");
      expect(tile).toHaveAttribute("data-kind", "butter");
      expect(tile).toHaveAttribute("aria-hidden");
      expect(tile).toHaveClass(tileSize, "bg-amber-100", "dark:bg-amber-950");
      expect(icon).toHaveAttribute("aria-hidden", "true");
      expect(icon).toHaveClass(iconSize);
      unmount();
    }
  });
});

describe("custom product icons", () => {
  it("renders every custom icon with the Lucide outline attributes", () => {
    for (const Icon of [Beet, Butter, Cucumber, Mushroom, Onion, Pepper, Potato, Tomato]) {
      const { container, unmount } = render(<Icon />);
      const icon = container.querySelector("svg");
      expect(icon).toHaveAttribute("viewBox", "0 0 24 24");
      expect(icon).toHaveAttribute("stroke", "currentColor");
      expect(icon).toHaveAttribute("fill", "none");
      unmount();
    }
  });
});

describe("ProductThumb with a brand", () => {
  it("shows the kind tile without a provider", () => {
    const { container } = render(<ProductThumb en="Valio milk 1 l" brand="Valio" />);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[data-kind]")).not.toBeNull();
  });

  it("shows the brand logo when it is known", async () => {
    const list = vi.fn(async (names: string[]) => names.map((name) => logo(name, name === "Valio")));
    const { container } = render(
      <ApiProvider api={withLogos(list)}>
        <ProductThumb en="Valio milk 1 l" brand="Valio" />
        <ProductThumb en="Arla milk 1 l" brand="Arla" />
      </ApiProvider>,
    );
    await waitFor(() => expect(container.querySelectorAll("img")).toHaveLength(1));
    expect(screen.getByAltText("Valio logo")).toHaveAttribute("src", URL);
    // Both brands went to the gateway in one call.
    expect(list).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledWith(["Valio", "Arla"]);
  });

  it("never asks for a brand name over 100 characters, and the others still get logos", async () => {
    const long = "B".repeat(101);
    const list = vi.fn(async (names: string[]) => names.map((name) => logo(name, true)));
    const { container } = render(
      <ApiProvider api={withLogos(list)}>
        <ProductThumb en="Valio milk 1 l" brand="Valio" />
        <ProductThumb en="Other milk 1 l" brand={long} />
      </ApiProvider>,
    );
    await waitFor(() => expect(container.querySelectorAll("img")).toHaveLength(1));
    expect(screen.getByAltText("Valio logo")).toHaveAttribute("src", URL);
    expect(list).toHaveBeenCalledTimes(1);
    expect(list).toHaveBeenCalledWith(["Valio"]);
  });

  it("never renders a blank tile: the kind icon stays under the logo, which shows only once loaded", async () => {
    const list = vi.fn(async (names: string[]) => names.map((name) => logo(name, true)));
    const { container } = render(
      <ApiProvider api={withLogos(list)}>
        <ProductThumb en="Valio Eila lactose free milk drink 1 L" brand="Valio Eila" size="sm" />
      </ApiProvider>,
    );
    const img = await screen.findByAltText("Valio Eila logo");
    const tile = container.querySelector("[data-kind]");
    expect(tile).toHaveAttribute("data-kind", "milk and cream");
    expect(tile?.querySelector(":scope > svg")).not.toBeNull();
    // The logo is a badge inside the kind tile, hidden while its image is still loading.
    const badge = tile?.querySelector('[data-logo="Valio Eila"]');
    expect(badge).toContainElement(img);
    expect(badge?.className).toMatch(/\binvisible\b/);
    fireEvent.load(img);
    expect(badge?.className).not.toMatch(/\binvisible\b/);
    expect(badge).toHaveAttribute("data-loaded");
    expect(tile?.querySelector(":scope > svg")).not.toBeNull();
  });

  it("goes back to the kind tile when the image does not load", async () => {
    const list = vi.fn(async (names: string[]) => names.map((name) => logo(name, true)));
    const { container } = render(
      <ApiProvider api={withLogos(list)}>
        <ProductThumb en="Valio milk 1 l" brand="Valio" />
      </ApiProvider>,
    );
    fireEvent.error(await screen.findByAltText("Valio logo"));
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("[data-logo]")).toBeNull();
    expect(container.querySelector("[data-kind] svg")).not.toBeNull();
  });

  it("keeps the kind tile when the logo list fails", async () => {
    const list = vi.fn(async () => {
      throw new Error("503");
    });
    const { container } = render(
      <ApiProvider api={withLogos(list)}>
        <ProductThumb en="Valio milk 1 l" brand="Valio" />
      </ApiProvider>,
    );
    await waitFor(() => expect(list).toHaveBeenCalled());
    expect(container.querySelector("img")).toBeNull();
  });

  it("never shows a logo that is not https", async () => {
    const list = vi.fn(async (names: string[]) =>
      names.map((name): BrandLogo => ({ ...logo(name, true), logoUrl: "javascript:alert(1)" })),
    );
    const { container } = render(
      <ApiProvider api={withLogos(list)}>
        <ProductThumb en="Valio milk 1 l" brand="Valio" />
      </ApiProvider>,
    );
    await waitFor(() => expect(list).toHaveBeenCalled());
    expect(container.querySelector("img")).toBeNull();
  });
});
