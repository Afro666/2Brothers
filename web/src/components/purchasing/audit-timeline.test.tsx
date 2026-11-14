import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { mapAudit } from "@/api/gateway-map";
import type { AuditEvent } from "@/types";

import { AuditTimeline, groupSteps, shortTitle } from "./audit-timeline";

const runId = "run-1";
const offerId = "offer-1";
const proposalId = "proposal-1";
const at = (second: number) => `2026-11-14T13:27:${String(second).padStart(2, "0")}+00:00`;
const sample = [
  { event_id: "search-start", run_id: runId, type: "tool_call_started", tool: "search_products", arguments: '{"query_present":true}', result: "{}", at: at(1) },
  { event_id: "search-finish", run_id: runId, type: "tool_call_finished", tool: "search_products", arguments: '{"query_present":true}', result: "{}", at: at(2) },
  {
    event_id: "offer-start",
    run_id: runId,
    type: "tool_call_started",
    tool: "get_offer",
    arguments: '{"product_ids":["463380","464073","464237"],"requested_date":"2026-11-16"}',
    result: "{}",
    at: at(3),
  },
  {
    event_id: "offer-finish",
    run_id: runId,
    type: "tool_call_finished",
    tool: "get_offer",
    arguments: '{"product_ids":["463380","464073","464237"],"requested_date":"2026-11-16"}',
    result: `{"offer_id":"${offerId}"}`,
    at: at(4),
  },
  { event_id: "simulate-start", run_id: runId, type: "tool_call_started", tool: "simulate_order", arguments: `{"offer_id":"${offerId}"}`, result: "{}", at: at(5) },
  { event_id: "simulate-finish", run_id: runId, type: "tool_call_finished", tool: "simulate_order", arguments: `{"offer_id":"${offerId}"}`, result: `{"offer_id":"${offerId}"}`, at: at(6) },
  { event_id: "approval-start", run_id: runId, type: "tool_call_started", tool: "request_approval", arguments: `{"offer_id":"${offerId}"}`, result: "{}", at: at(7) },
  { event_id: "approval-requested", kind: "approval_requested", actor: "buyer-agent", proposal_id: proposalId, offer_id: `"${offerId}"`, expected_total: '"601.55"', at: at(8) },
  {
    event_id: "decision",
    kind: "decision_summary",
    actor: "buyer-agent",
    proposal_id: proposalId,
    offer_id: `"${offerId}"`,
    summary: 'Asked: "200 liters lactose-free milk by Monday" (200 L for 2026-11-16).\nChecked 3 products.',
    at: at(9),
  },
  { event_id: "approval-finish", run_id: runId, type: "tool_call_finished", tool: "request_approval", arguments: `{"offer_id":"${offerId}"}`, result: '{"status":"PENDING"}', at: at(10) },
  { event_id: "placed", kind: "order_placed", actor: "human", proposal_id: proposalId, order_id: "order-1", expected_total: '"601.55"', at: "2026-11-14T13:32:03+00:00" },
];

describe("AuditTimeline", () => {
  it("shows the raw kind and actor when the app does not know them", () => {
    const event = {
      id: "e1",
      at: "2026-11-14T10:00:00Z",
      kind: "tool_call",
      actor: "mcp_client",
      summary: "Called search_products",
      reason: "Agent looked for milk",
    } as unknown as AuditEvent;
    render(<AuditTimeline events={[event]} />);
    expect(screen.getByText("tool_call")).toBeInTheDocument();
    expect(screen.getByText("mcp_client")).toBeInTheDocument();
    expect(screen.getByText("Called search_products")).toBeInTheDocument();
  });

  it("says which account took a step, when the step has one", () => {
    const step = { id: "e1", at: "2026-11-14T10:00:00Z", kind: "order", summary: "Order placed", reason: "expected_total: 173.76" };
    render(
      <AuditTimeline
        events={[
          { ...step, actor: "human", actorName: "approver@example.test" },
          { ...step, id: "e2", actor: "agent" },
        ] as AuditEvent[]}
      />,
    );
    expect(screen.getByText("By approver@example.test")).toBeInTheDocument();
    expect(screen.getAllByText(/^By /)).toHaveLength(1);
  });

  it("groups the real sample into one readable request with six collapsed steps", () => {
    const groups = groupSteps(mapAudit(sample));
    expect(groups).toHaveLength(1);
    expect(groups[0].title).toContain("200 liters lactose-free milk");
    expect(groups[0].outcome).toBe("order placed");
    expect(groups[0].total).toBe("601.55");
    expect(groups[0].at).toBe("2026-11-14T13:32:03+00:00");
    expect(groups[0].rows.length).toBeLessThanOrEqual(6);
    expect(groups[0].rows.map((event) => event.summary)).toEqual([
      "Buyer searched the catalog",
      "Buyer got the offer",
      "Buyer simulated the order",
      "Approval requested",
      "Buyer asked for approval",
      "Order placed",
    ]);
    expect(groups[0].rows.find((event) => event.summary === "Buyer got the offer")?.reason).toBe(
      "3 products for Mon 16 Nov",
    );
  });

  it("keeps id-less rows apart, sorts known blocks newest first, and joins ids transitively", () => {
    const event = (id: string, at: string | null, groupIds?: string[]): AuditEvent => ({
      id,
      at,
      kind: "other",
      actor: "system",
      summary: id,
      reason: "",
      groupIds,
    });
    const groups = groupSteps([
      event("unknown stays first", null),
      event("old", "2026-11-13T10:00:00Z", ["run-a"]),
      event("bridge", "2026-11-13T11:00:00Z", ["run-a", "offer-a"]),
      event("connected", "2026-11-13T12:00:00Z", ["offer-a"]),
      event("separate run", "2026-11-14T10:00:00Z", ["run-b"]),
      event("no ids", "2026-11-14T11:00:00Z"),
    ]);
    expect(groups.map((group) => group.title)).toEqual([
      "unknown stays first",
      "no ids",
      "separate run",
      "old",
    ]);
    expect(groups.at(-1)?.rows.map((row) => row.id)).toEqual(["old", "bridge", "connected"]);
    expect(groups.filter((group) => group.events.some((row) => row.groupIds?.includes("run-b")))).toHaveLength(1);
  });

  it("uses the failed finished wording for a collapsed call and keeps an unfinished call", () => {
    const groups = groupSteps(
      mapAudit([
        { event_id: "start", run_id: "failed-run", type: "tool_call_started", tool: "get_offer", arguments: {}, at: at(1) },
        {
          event_id: "finish",
          run_id: "failed-run",
          type: "tool_call_finished",
          tool: "get_offer",
          arguments: {},
          result: { error: "No offer" },
          at: at(2),
        },
        { event_id: "unfinished", run_id: "other-run", type: "tool_call_started", tool: "search_products", arguments: {}, at: at(3) },
      ]),
    );
    const failed = groups.flatMap((group) => group.rows).find((event) => event.id === "finish");
    expect(failed?.summary).toBe("Buyer got the offer: it failed");
    expect(failed?.details).toContain("error: No offer");
    expect(groups.flatMap((group) => group.rows).filter((event) => event.kind === "offer")).toHaveLength(1);
    expect(groups.flatMap((group) => group.rows).some((event) => event.summary === "Buyer is searching the catalog")).toBe(true);
  });

  it("shows what was asked as the heading and the whole summary under it", () => {
    const events = mapAudit(sample);
    render(<AuditTimeline events={events} groups={groupSteps(events)} />);
    expect(screen.getByRole("heading", { name: "200 liters lactose-free milk by Monday" })).toBeInTheDocument();
    expect(screen.getByText(/^Asked: "200 liters lactose-free milk by Monday" \(200 L for 2026-11-16\)\./)).toHaveTextContent(
      "Checked 3 products.",
    );
  });

  it("titles a block with what was asked, not with the whole decision summary", () => {
    expect(
      shortTitle('Asked: "20L oat drink for monday" (20 L for 2026-11-16). Checked 3 product(s) with Valio prices.'),
    ).toBe("20L oat drink for monday");
    expect(shortTitle("ORD-1043 needs approval (€1,947.50 ex VAT)")).toBe("ORD-1043 needs approval (€1,947.50 ex VAT)");
    expect(shortTitle(`${"A long first sentence ".repeat(10)}. Second.`).length).toBeLessThanOrEqual(120);
  });
});
