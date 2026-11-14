import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { ApiError } from "@/api";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("trust page", () => {
  beforeEach(() => localStorage.clear());

  it("verifies, shows the break on the tampered line, and is OK again after restore", async () => {
    const user = userEvent.setup();
    renderApp("/trust");
    const lines = within(await screen.findByRole("region", { name: "Newest audit lines" }));
    expect(await lines.findByText("Line 8")).toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText(/MongoDB Atlas/)).not.toBeInTheDocument();
    const result = within(screen.getByRole("status"));
    expect(result.getByText("Not checked yet.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Verify audit chain" }));
    expect(await result.findByText("Chain OK: 8 lines checked")).toBeInTheDocument();
    expect(lines.queryByText("Broken here")).not.toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Tamper with one line" }));
    expect(await lines.findByText("Asked the buyer to approve ORD-1043 (edited after the fact)")).toBeInTheDocument();
    expect(result.getByText("Not checked yet.")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Verify audit chain" }));
    expect(await result.findByText("Chain broken at line 8: 7 lines before it are intact")).toBeInTheDocument();
    expect(lines.getByText("Broken here")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(await lines.findByText("Asked the buyer to approve ORD-1043")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Verify audit chain" }));
    expect(await result.findByText("Chain OK: 8 lines checked")).toBeInTheDocument();
    expect(lines.queryByText("Broken here")).not.toBeInTheDocument();
  });

  it("names MongoDB Atlas only when the gateway answers the verify", async () => {
    renderApp("/trust", Object.assign(createMockApi(), { live: new Set(["verifyAuditChain" as const]) }));
    expect(await screen.findByText("Audit log stored in MongoDB Atlas")).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("says so when the break is in another kitchen's entry", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    api.verifyAuditChain = async () => ({
      ok: false,
      length: 411,
      brokenAt: 412,
      brokenKitchenId: "another-kitchen",
      kitchenEntries: 57,
      checkedAt: "2026-11-14T10:00:00Z",
    });
    renderApp("/trust", api);
    await user.click(await screen.findByRole("button", { name: "Verify audit chain" }));
    const result = within(screen.getByRole("status"));
    expect(
      await result.findByText("The break is in another kitchen's entry (the demo), not in yours"),
    ).toBeInTheDocument();
    expect(
      result.getByText(/It is line 412 of the shared log\. 57 of the lines are this kitchen's\./),
    ).toBeInTheDocument();
    expect(result.queryByText(/Chain broken/)).not.toBeInTheDocument();
  });

  it("says a refused tamper in plain words", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    api.tamperAuditRow = async () => {
      throw new ApiError("DEMO_ONLY", "demo_only");
    };
    renderApp("/trust", api);
    await user.click(await screen.findByRole("button", { name: "Tamper with one line" }));
    expect(await screen.findByText("The tamper demo only runs on the demo kitchen.")).toBeInTheDocument();
  });

  it("offers a retry when the lines cannot be read", async () => {
    const api = createMockApi();
    api.listAuditChain = async () => {
      throw new ApiError("NETWORK", "Could not reach the gateway.");
    };
    renderApp("/trust", api);
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the gateway.");
  });
});
