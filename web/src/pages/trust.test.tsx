import { cleanup, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/api";
import type { AuditChainRow } from "@/api/types";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("trust page", () => {
  beforeEach(() => localStorage.clear());
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("puts the verify button before the label checks", async () => {
    vi.stubEnv("VITE_LIVE_BUYER", "true");
    vi.stubGlobal("fetch", () => new Promise(() => {}));
    renderApp("/trust");
    const button = await screen.findByRole("button", { name: "Verify audit chain" });
    const heading = screen.getByRole("heading", { name: "Source-backed label checks" });
    expect(button.compareDocumentPosition(heading) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
  });

  it("checks the chain when the page opens and checks again from the button", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    const verify = vi.spyOn(api, "verifyAuditChain");
    renderApp("/trust", api);

    const initialResult = await screen.findByText("Audit log intact: each of the 8 entries carries the hash of the one before it");
    expect(initialResult).toBeInTheDocument();
    const result = within(initialResult.closest("[role=status]") as HTMLElement);
    expect(verify).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Verify audit chain" }));
    await vi.waitFor(() => expect(verify).toHaveBeenCalledTimes(2));
    expect(result.getByText("Audit log intact: each of the 8 entries carries the hash of the one before it")).toBeInTheDocument();
  });

  it("shows the existing error state when the opening check fails", async () => {
    const api = createMockApi();
    api.verifyAuditChain = async () => {
      throw new ApiError("NETWORK", "Could not reach the gateway.");
    };
    renderApp("/trust", api);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the gateway.");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
    expect(screen.queryByText(/Chain OK/)).not.toBeInTheDocument();
  });

  it("uses a plain label when an audit summary is a raw code", async () => {
    const api = createMockApi();
    api.listAuditChain = async () => [
      {
        seq: 1,
        event: { id: "label-1", at: "2026-11-14T10:00:00Z", kind: "other", actor: "system", summary: "kitchen_brief_read", reason: "" },
        prevHash: "a".repeat(64),
        hash: "b".repeat(64),
      },
    ];
    renderApp("/trust", api);

    expect(await screen.findByText("Kitchen brief read")).toBeInTheDocument();
    expect(screen.queryByText("kitchen_brief_read")).not.toBeInTheDocument();
  });

  it("says how many entries belong to other kitchens, and leaves the count unknown when the numbers do not add up", async () => {
    const api = createMockApi();
    api.verifyAuditChain = async () => ({
      ok: true,
      length: 1535,
      brokenAt: null,
      brokenKitchenId: null,
      kitchenEntries: 1500,
      checkedAt: "2026-11-14T10:00:00Z",
    });
    renderApp("/trust", api);
    expect(await screen.findByText(/^1500 of the 1535 entries belong to this kitchen; the others belong to other kitchens or the system\. Checked at ./)).toBeInTheDocument();
    cleanup();

    api.verifyAuditChain = async () => ({
      ok: true,
      length: 10,
      brokenAt: null,
      brokenKitchenId: null,
      kitchenEntries: 20,
      checkedAt: "2026-11-14T10:00:00Z",
    });
    renderApp("/trust", api);
    expect(await screen.findByText(/How many entries belong to this kitchen: unknown\. Checked at/)).toBeInTheDocument();
    expect(screen.queryByText(/20 of the 10/)).not.toBeInTheDocument();
  });

  it("shows camelCase step names and actor names as plain words, in both languages", async () => {
    const api = createMockApi();
    // The five newest lines as a stranger saw them: raw step codes and a raw actor name.
    const steps: [string, string, string][] = [
      ["proposal_changed", "system", ""],
      ["proposalChanged", "system", ""],
      ["Proposal explanation failed", "buyer-agent", "system"],
      ["approval_token_created", "human", ""],
      ["Order status checked", "order_resolved", "checked"],
    ];
    api.listAuditChain = async () =>
      steps.map(([summary, actor, reason], index) => ({
        seq: index + 1,
        event: {
          id: `step-${index}`,
          at: "2026-11-14T10:00:00Z",
          kind: "other",
          actor: actor as AuditChainRow["event"]["actor"],
          summary,
          reason,
        },
        prevHash: "a".repeat(64),
        hash: "b".repeat(64),
      }));
    renderApp("/trust", api);
    const lines = within(await screen.findByRole("region", { name: "Newest audit lines" }));
    expect(await lines.findByText("Proposal changed")).toBeInTheDocument();
    expect(lines.getByText("Proposal explanation failed")).toBeInTheDocument();
    expect(lines.getByText("Approval token created")).toBeInTheDocument();
    expect(lines.getByText("Order status checked")).toBeInTheDocument();
    expect(lines.getByText("proposalChanged")).toBeInTheDocument();
    // The raw code stays only above, as a plain sentence the page did not write.
    expect(lines.queryByText("proposal_changed")).not.toBeInTheDocument();
    expect(lines.queryByText("approval_token_created")).not.toBeInTheDocument();
    cleanup();
    localStorage.setItem("purchasing-language", "fi");
    renderApp("/trust", api);
    const suomi = within(await screen.findByRole("region", { name: "Uusimmat lokirivit" }));
    expect(await suomi.findByText("Ehdotusta muutettiin")).toBeInTheDocument();
  });

  it("shows loading instead of an unchecked result during the opening check", async () => {
    const api = createMockApi();
    api.verifyAuditChain = () => new Promise(() => {});
    renderApp("/trust", api);

    expect(await screen.findByText("Loading audit lines")).toBeInTheDocument();
    expect(screen.queryByText("Not checked yet.")).not.toBeInTheDocument();
  });

  it("verifies, shows the break on the tampered line, and is OK again after restore", async () => {
    const user = userEvent.setup();
    renderApp("/trust");
    const lines = within(await screen.findByRole("region", { name: "Newest audit lines" }));
    expect(await lines.findByText("Line 8")).toBeInTheDocument();
    expect(screen.getByText("Sample data")).toBeInTheDocument();
    expect(screen.queryByText(/MongoDB Atlas/)).not.toBeInTheDocument();
    const result = within(screen.getByRole("status"));
    expect(await result.findByText("Audit log intact: each of the 8 entries carries the hash of the one before it")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Verify audit chain" }));
    expect(await result.findByText("Audit log intact: each of the 8 entries carries the hash of the one before it")).toBeInTheDocument();
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
    expect(await result.findByText("Audit log intact: each of the 8 entries carries the hash of the one before it")).toBeInTheDocument();
    expect(lines.queryByText("Broken here")).not.toBeInTheDocument();
  });

  it("names MongoDB Atlas only when the gateway answers the verify", async () => {
    renderApp("/trust", Object.assign(createMockApi(), { live: new Set(["verifyAuditChain" as const]) }));
    expect(await screen.findByText("Audit log stored in MongoDB Atlas")).toBeInTheDocument();
    expect(screen.queryByText("Sample data")).not.toBeInTheDocument();
  });

  it("says so when the break is in another kitchen's entry", async () => {
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
    expect(
      await screen.findByText("The break is in another kitchen's entry (the demo), not in yours"),
    ).toBeInTheDocument();
    expect(
      screen.getByText(/It is line 412 of the shared log\. 57 of the \d+ entries belong to this kitchen; the others belong to other kitchens or the system\./),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Chain broken/)).not.toBeInTheDocument();
  });

  it("says a refused tamper in plain words", async () => {
    const user = userEvent.setup();
    const api = createMockApi();
    api.tamperAuditRow = async () => {
      throw new ApiError("DEMO_ONLY", "demo_only");
    };
    renderApp("/trust", api);
    expect(await screen.findByText("Audit log intact: each of the 8 entries carries the hash of the one before it")).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Tamper with one line" }));
    expect(await screen.findByText("The tamper demo only runs on the demo kitchen.")).toBeInTheDocument();
  });

  it("offers a retry when the lines cannot be read", async () => {
    const api = createMockApi();
    api.listAuditChain = async () => {
      throw new ApiError("NETWORK", "Could not reach the gateway.");
    };
    renderApp("/trust", api);
    expect(await screen.findByRole("alert", {}, { timeout: 5000 })).toHaveTextContent("Could not reach the gateway.");
  });
});
