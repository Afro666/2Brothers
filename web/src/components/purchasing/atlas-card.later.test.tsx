import { screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

import { renderApp } from "@/test/render";

// A comparison measured after the ranking change (#1953): its own file, because the mock is file-wide.
vi.mock("@/data/atlas-search-comparison.json", async (original) => {
  const actual = (await original()) as { default: Record<string, unknown> };
  return { default: { ...actual.default, measured_on: "2026-11-15" } };
});

it("does not say a later comparison predates the ranking change", async () => {
  localStorage.clear();
  renderApp("/about");
  // The caption in the fold still gives the date.
  expect(
    await screen.findByText("The top 8 results for 10 searches, measured on the server on 2026-11-15."),
  ).toBeInTheDocument();
  expect(screen.getByText("Show the 10 searches")).toBeInTheDocument();
  expect(screen.queryByText(/before the search ranking was changed/)).not.toBeInTheDocument();
});
