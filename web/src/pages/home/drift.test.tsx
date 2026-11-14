import { act, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { createMockApi } from "@/api/mock";
import { ApiError } from "@/api/types";
import { renderApp } from "@/test/render";
import type { DriftWarning } from "@/types";

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
    const api = createMockApi();
    await api.signIn("planner@demo.valio", "demo-kitchen-2026");
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(
      await screen.findByText(/K04 Hotel Aurora Helsinki/),
    ).toBeInTheDocument();
    expect(screen.getByText("Price creeping +22%")).toBeInTheDocument();
  });

  it("hides the tile while the gateway does not serve the route", async () => {
    let rejectDrift!: (reason: ApiError) => void;
    const driftRequest = new Promise<never>((_resolve, reject) => {
      rejectDrift = reject;
    });
    const api = {
      ...createMockApi(),
      getDrift: () => driftRequest,
    };
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(await screen.findByText("Waiting for your approval")).toBeInTheDocument();
    await act(async () => {
      rejectDrift(new ApiError("NOT_SERVED", "The gateway does not serve this yet."));
      await driftRequest.catch(() => undefined);
    });
    await waitFor(() => expect(screen.queryByText(/Standing-order drift/)).not.toBeInTheDocument());
  });

  it("hides the tile when drift is unavailable", async () => {
    const api = {
      ...createMockApi(),
      getDrift: async () => {
        throw new ApiError(
          "DRIFT_UNAVAILABLE",
          "Drift cannot be computed right now.",
        );
      },
    };
    renderApp(`/?now=${DEMO_NOW}`, api);

    expect(
      await screen.findByText("Waiting for your approval"),
    ).toBeInTheDocument();
    await waitFor(() => expect(screen.queryByText(/Standing-order drift/)).not.toBeInTheDocument());
    await waitFor(() => expect(screen.queryByText(/Orders per guest are steady/)).not.toBeInTheDocument());
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

  it("keeps both rows when one product creeps in portion and price", async () => {
    const base: DriftWarning = {
      productId: "P1",
      productName: "Milk 1 l",
      kind: "portion_creep",
      change: 0.4,
      unit: "ST",
      qtyPer100: 14,
      baselineQty: 10,
      spendPer100: 20,
      baselineSpend: 15,
      baselineWeeks: 4,
      why: "Portion why",
    };
    const api = {
      ...createMockApi(),
      getDrift: async () => ({
        week: "2026-11-09",
        warnings: [
          base,
          { ...base, kind: "cost_creep" as const, change: 0.3, why: "Cost why" },
        ],
      }),
    };
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    try {
      renderApp(`/?now=${DEMO_NOW}`, api);

      expect(await screen.findByText("Portion why")).toBeInTheDocument();
      expect(screen.getByText("Cost why")).toBeInTheDocument();
      const duplicateKey = errors.mock.calls.some((call) =>
        call.some((arg) => String(arg).includes("same key")),
      );
      expect(duplicateKey).toBe(false);
    } finally {
      errors.mockRestore();
    }
  });
});
