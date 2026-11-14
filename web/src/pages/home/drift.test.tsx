import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";
import { renderApp } from "@/test/render";

const DEMO_NOW = "2026-11-13T21:00:00%2B02:00";

describe("Standing-order drift tiles", () => {
  beforeEach(() => localStorage.clear());

  it("shows the kitchen's portion and price creep with the why", async () => {
    renderApp(`/?now=${DEMO_NOW}`, createMockApi());

    expect(
      await screen.findByText("Portions creeping +40%"),
    ).toBeInTheDocument();
    expect(screen.getByText("Price creeping +30%")).toBeInTheDocument();
    expect(
      screen.getByText(/14\.0 ST per 100 guests last week/),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Check the next order" }),
    ).toHaveAttribute("href", "/approvals");
  });

  it("names the consenting kitchen on the Valio side", async () => {
    localStorage.setItem("purchasing-role", "valio_planner");
    renderApp(`/?now=${DEMO_NOW}`, createMockApi());

    expect(
      await screen.findByText(/K04 Hotel Aurora Helsinki/),
    ).toBeInTheDocument();
    expect(screen.getByText("Price creeping +22%")).toBeInTheDocument();
  });

  it("hides the tile while the gateway does not serve the route", async () => {
    const api = {
      ...createMockApi(),
      getDrift: async () => {
        throw new ApiError(
          "NOT_SERVED",
          "The gateway does not serve this yet.",
        );
      },
    };
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(
      await screen.findByText("Waiting for your approval"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Standing-order drift/)).not.toBeInTheDocument();
  });

  it("says so when nothing drifts", async () => {
    const api = {
      ...createMockApi(),
      getDrift: async () => ({ week: "2026-11-09", warnings: [] }),
    };
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(
      await screen.findByText(
        "Orders per guest are steady. Nothing to check before renewal.",
      ),
    ).toBeInTheDocument();
  });
});
