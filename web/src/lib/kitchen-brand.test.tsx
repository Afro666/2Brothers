import { renderHook } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { safeLogoUrl, saveKitchenBrand, useKitchenBrand } from "@/lib/kitchen-brand";
import type { KitchenBrandProfile } from "@/types";

afterEach(() => localStorage.clear());

it("ignores malformed persisted profiles instead of crashing the app shell", () => {
  localStorage.setItem("kitchen-brand", JSON.stringify({ name: "Kitchen", logoUrl: 42 }));
  const { result } = renderHook(() => useKitchenBrand());
  expect(result.current).toBeNull();
  expect(safeLogoUrl(42)).toBeNull();
  expect(safeLogoUrl({ trim: true })).toBeNull();
});

it("reads valid saved profiles and only permits supported logo URLs", () => {
  const profile: KitchenBrandProfile = { name: "Kitchen", domain: "example.test", logoUrl: "https://example.test/logo.png",
    colors: ["#ffffff"], address: { street: null, postalCode: null, city: null, country: null }, kitchenType: null, openingHours: null };
  saveKitchenBrand(profile);
  const { result } = renderHook(() => useKitchenBrand());
  expect(result.current).toEqual(profile);
  expect(safeLogoUrl(profile.logoUrl)).toBe(profile.logoUrl);
  expect(safeLogoUrl("javascript:alert(1)")).toBeNull();
});
