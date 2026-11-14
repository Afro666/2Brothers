import { act, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it } from "vitest";

import { mapAudit } from "@/api/gateway-map";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

describe("audit page", () => {
  beforeEach(() => localStorage.clear());

  it("groups the milk-case requests, keeps their steps in time order, and sorts blocks newest first", async () => {
    renderApp("/audit");
    const requestTitle = await screen.findByRole("heading", { name: "1,000 L lactose-free milk by Monday" });
    const request = requestTitle.closest("section")!;
    const summaries = within(request).getAllByText(/lactose-free milk|Searched|Price and availability|Split:/);

    expect(summaries[0]).toHaveTextContent("1,000 L lactose-free milk by Monday");
    expect(summaries.at(-1)).toHaveTextContent("Split:");
    const headings = screen.getAllByRole("heading", { level: 2 }).map((heading) => heading.textContent);
    expect(headings).toEqual([
      "ORD-1043 needs approval (€1,947.50 ex VAT)",
      "Head chef approved ORD-1042 (€131.07 ex VAT)",
      "1,000 L lactose-free milk by Monday",
    ]);
    expect(screen.getByText("Asked the buyer to approve ORD-1043")).toBeInTheDocument();
    expect(screen.getByText("3 requests, 8 steps")).toBeInTheDocument();
  });

  it.each([999, 1000])("describes the gateway limit at %i steps", async (count) => {
    const api = createMockApi();
    api.listAudit = async () => Array.from({ length: count }, (_, index) => ({
      id: `event-${index}`,
      at: new Date(Date.UTC(2026, 10, 14, 0, 0, index)).toISOString(),
      kind: "other" as const,
      actor: "system" as const,
      summary: `Step ${index}`,
      reason: "",
    }));
    renderApp("/audit", api);

    expect(await screen.findByText(
      count === 1000 ? "1000 requests, the newest 1,000 steps" : "999 requests, 999 steps",
    )).toBeInTheDocument();
  });

  it("names products instead of showing their ids", async () => {
    renderApp("/audit");
    expect(
      await screen.findByText(
        "Split: 51 ST of Arla 1 L lactose free fat free UHT milk drink and 950 ST of Valio Eila 3 % lactose free milk drink 1 L",
      ),
    ).toBeInTheDocument();
    expect(screen.queryByText(/462775|463335/)).not.toBeInTheDocument();
  });

  it("filters by order and restores all steps with Clear filters", async () => {
    const user = userEvent.setup();
    renderApp("/audit");
    await screen.findByText("3 requests, 8 steps");

    await user.click(screen.getByRole("combobox", { name: "Order" }));
    await user.click(await screen.findByRole("option", { name: "ORD-1042" }));
    expect(await screen.findByText("1 request, 2 steps")).toBeInTheDocument();
    expect(screen.getByText("ORD-1042 placed for Mon 16 Nov")).toBeInTheDocument();
    expect(screen.queryByText("Asked the buyer to approve ORD-1043")).not.toBeInTheDocument();

    await user.click(screen.getByRole("combobox", { name: "Actor" }));
    await user.click(await screen.findByRole("option", { name: "Valio" }));
    expect(await screen.findByText("No audit steps match these filters")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Clear filters" }));
    expect(await screen.findByText("3 requests, 8 steps")).toBeInTheDocument();
    expect(screen.getByText("Asked the buyer to approve ORD-1043")).toBeInTheDocument();
  });

  it("preserves source order when event times are equal", async () => {
    const api = createMockApi();
    const listAudit = api.listAudit.bind(api);
    api.listAudit = async (filter) => {
      const events = await listAudit(filter);
      return [
        { ...events[1], id: "same-a", at: events[0].at, summary: "First at same time", groupIds: [] },
        { ...events[0], id: "same-b", at: events[0].at, summary: "Second at same time", groupIds: [] },
      ];
    };
    renderApp("/audit", api);
    await screen.findByRole("heading", { name: "First at same time" });
    const headings = screen.getAllByRole("heading", { level: 2 }).filter((heading) => heading.textContent?.includes("same time"));
    expect(headings[0]).toHaveTextContent("First at same time");
    expect(headings[1]).toHaveTextContent("Second at same time");
    const first = screen.getByRole("heading", { name: "First at same time" }).closest("section")!;
    const second = screen.getByRole("heading", { name: "Second at same time" }).closest("section")!;
    expect(within(first).getAllByText("First at same time")).toHaveLength(1);
    expect(within(second).getAllByText("Second at same time")).toHaveLength(1);
  });

  it("shows a plain-English label for the kinds and tools added on 14 Nov; unknown ones keep their name (#899)", async () => {
    const labels: Record<string, string> = {
      stock_photo_read: "Shelf photo read by Nemotron VL",
      audit_demo_tamper: "Tamper demo: a line was changed",
      audit_demo_restore: "Tamper demo: the line was restored",
      option_chosen: "A person chose an option",
      order_lookup: "A person looked up an order with an unknown send result",
      order_resolved: "A person resolved an unknown send",
      recall_check: "Recall check",
      demo_inbox_cleared: "Test proposals cleared before a demo",
      delivery_note_read: "Delivery note read",
      proposal_explanation_failed: "Proposal explanation failed",
      kitchen_brief_read: "Kitchen brief read",
      some_future_kind: "some_future_kind",
    };
    const raw = [
      ...Object.keys(labels).map((kind, i) => ({
        event_id: `k-${i}`,
        kind,
        actor: "system",
        ...(kind === "proposal_explanation_failed" ? { reason: "EXPLANATION_UNAVAILABLE" } : {}),
        ...(kind === "order_lookup" ? { reason: "BLOCKED_BY_RECALL" } : {}),
        at: `2026-11-14T10:${String(i).padStart(2, "0")}:00+00:00`,
      })),
      { event_id: "t-1", type: "tool_call_finished", tool: "request_approval", arguments: {}, result: {} },
      { event_id: "t-2", type: "tool_call_finished", tool: "simulate_order", arguments: {}, result: {} },
      { event_id: "t-3", type: "tool_call_started", tool: "request_approval", arguments: {} },
      { event_id: "t-4", type: "tool_call_finished", tool: "new_tool", arguments: {}, result: {} },
    ];
    const api = createMockApi();
    api.listAudit = async () => mapAudit(raw);
    renderApp("/audit", api);

    for (const label of Object.values(labels)) expect(await screen.findAllByText(label)).toHaveLength(1);
    expect(screen.getAllByText("Buyer asked for approval")).toHaveLength(1);
    expect(screen.getAllByText("Buyer simulated the order")).toHaveLength(1);
    expect(screen.getAllByText("Buyer is asking for approval")).toHaveLength(1);
    expect(screen.getAllByText("new_tool finished")).toHaveLength(1);
    // A reason code reads as its plain name, without the approval card's present-tense advice.
    expect(screen.getByText("Explanation unavailable")).toBeInTheDocument();
    expect(screen.getByText("Blocked by a recall")).toBeInTheDocument();
    expect(screen.queryByText(/EXPLANATION_UNAVAILABLE|BLOCKED_BY_RECALL|It cannot be approved/)).not.toBeInTheDocument();
    for (const name of ["stock_photo_read", "request_approval finished", "Buyer called request_approval"]) {
      expect(screen.queryByText(name)).not.toBeInTheDocument();
    }
  });

  it("follows later ?kind= changes without remounting and ignores unknown kinds", async () => {
    const { router } = renderApp("/audit?kind=search");
    const kind = await screen.findByRole("combobox", { name: "Kind" });
    expect(kind).toHaveTextContent("Search");

    await act(() => router.navigate({ to: "/audit", search: { kind: "offer" } as never }));
    expect(screen.getByRole("combobox", { name: "Kind" })).toBe(kind);
    await waitFor(() => expect(kind).toHaveTextContent("Offer"));

    await act(() => router.navigate({ to: "/audit", search: { kind: "bogus" } as never }));
    await waitFor(() => expect(kind).toHaveTextContent("All kinds"));
  });
  it("pages requests instead of splitting their steps with Show more (#1142)", async () => {
    const api = createMockApi();
    api.listAudit = async () =>
      Array.from({ length: 120 }, (_, i) => ({
        id: `ev-${i}`,
        at: new Date(Date.UTC(2026, 10, 14, 0, i)).toISOString(),
        kind: "other" as const,
        actor: "system" as const,
        summary: `Step number ${i}`,
        reason: "",
      }));
    renderApp("/audit", api);

    expect(await screen.findAllByText("Step number 119")).toHaveLength(1);
    expect(screen.getAllByText("Step number 70")).toHaveLength(1);
    expect(screen.queryByText("Step number 69")).not.toBeInTheDocument();
    expect(screen.getByText("120 requests, 120 steps")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Show more (70 earlier requests)" }));
    expect(screen.getAllByText("Step number 20")).toHaveLength(1);
    await userEvent.click(screen.getByRole("button", { name: "Show more (20 earlier requests)" }));
    expect(screen.getAllByText("Step number 0")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: /Show more/ })).not.toBeInTheDocument();
  });

  it("hides raw fields in closed Details and reveals collapsed steps on request", async () => {
    const api = createMockApi();
    api.listAudit = async () =>
      mapAudit([
        { event_id: "s1", run_id: "run", type: "tool_call_started", tool: "search_products", arguments: {}, at: "2026-11-14T10:00:00Z" },
        { event_id: "s2", run_id: "run", type: "tool_call_finished", tool: "search_products", arguments: {}, result: {}, at: "2026-11-14T10:01:00Z" },
        { event_id: "o1", run_id: "run", type: "tool_call_started", tool: "get_offer", arguments: { product_ids: ["1"] }, at: "2026-11-14T10:02:00Z" },
        { event_id: "o2", run_id: "run", type: "tool_call_finished", tool: "get_offer", arguments: { product_ids: ["1"] }, result: { offer_id: "offer-secret" }, at: "2026-11-14T10:03:00Z" },
        { event_id: "m1", run_id: "run", type: "tool_call_started", tool: "simulate_order", arguments: { offer_id: "offer-secret" }, at: "2026-11-14T10:04:00Z" },
        { event_id: "m2", run_id: "run", type: "tool_call_finished", tool: "simulate_order", arguments: { offer_id: "offer-secret" }, result: { offer_id: "offer-secret" }, at: "2026-11-14T10:05:00Z" },
        { event_id: "a1", run_id: "run", type: "tool_call_started", tool: "request_approval", arguments: { offer_id: "offer-secret" }, at: "2026-11-14T10:06:00Z" },
        { event_id: "a2", run_id: "run", type: "tool_call_finished", tool: "request_approval", arguments: { offer_id: "offer-secret" }, result: { offer_id: "offer-secret" }, at: "2026-11-14T10:07:00Z" },
        { event_id: "approval", kind: "approval_requested", actor: "buyer-agent", proposal_id: "proposal", offer_id: "offer-secret", at: "2026-11-14T10:08:00Z" },
        { event_id: "order", kind: "order_placed", actor: "human", proposal_id: "proposal", order_id: "order", at: "2026-11-14T10:09:00Z" },
      ]);
    const user = userEvent.setup();
    renderApp("/audit", api);

    expect(await screen.findByRole("heading", { name: "Buyer is searching the catalog" })).toBeInTheDocument();
    expect(screen.queryByText("Buyer got the offer")).not.toBeInTheDocument();
    expect(screen.getByText("1 request, 6 steps")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Buyer is searching the catalog" }).closest("section")).toHaveTextContent(
      "Order placed",
    );
    for (const raw of screen.queryAllByText(/offer_id/)) expect(raw).not.toBeVisible();

    await user.click(screen.getByRole("button", { name: "Show all 6 steps" }));
    expect(screen.getByText("Buyer got the offer")).toBeVisible();
    const offerRow = screen.getByText("Buyer got the offer").closest("li")!;
    expect(within(offerRow).getByText(/offer_id/)).not.toBeVisible();
    await user.click(within(offerRow).getByText("Details"));
    expect(within(offerRow).getByText(/offer_id/)).toBeVisible();
  });
});
