import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { createMockApi } from "@/api/mock";
import { renderApp } from "@/test/render";

const row = {
  proposal_id: "p1", offer_id: "o1", status: "READY", valid_until: "2099-01-01T00:00:00Z",
  expected_total: "149.02", total_ex_vat: "131.07",
  lines: [{ product_id: "462775", quantity: "51", unit: "ST", why: "Measured stock", unknown_stock: false }],
};
beforeEach(() => vi.stubEnv("VITE_LIVE_BUYER", "true"));
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
const json = (body: unknown) => new Response(JSON.stringify(body));

it("requires confirmation to close a recall-held proposal without dismissing its notice", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json({ proposals: [{ ...row, status: "BLOCKED_BY_RECALL" }] }))
    .mockResolvedValueOnce(json({ status: "REJECTED", proposal_id: "p1" }));
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  renderApp("/approvals");
  await user.click(await screen.findByRole("button", { name: "Reject proposal" }));
  expect(fetch).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: /Approve .*149/ })).toBeNull();
  await user.click(screen.getByRole("button", { name: "Confirm rejection" }));
  expect((await screen.findAllByText("REJECTED")).length).toBeGreaterThan(0);
  expect(fetch.mock.calls[1][0]).toBe("/api/v1/kitchens/demo-kitchen/proposals/p1/reject");
  expect(fetch.mock.calls.some(c => String(c[0]).includes("/dismiss"))).toBe(false);
});

it("requires a pack-check reason before dismissal and keeps the original basket unapprovable", async () => {
  const alert = { event_id: "recall1", product_id: "462775", match: "possible", recall: { url: "https://www.ruokavirasto.fi/notice", lot: "Lot 2027" } };
  const held = { ...row, status: "BLOCKED_BY_RECALL", recall_alerts: [alert] };
  const fetch = vi.fn().mockResolvedValueOnce(json({ proposals: [held] }))
    .mockResolvedValueOnce(json({ event_id: "recall1", status: "dismissed" }))
    .mockResolvedValueOnce(json({ proposals: [{ ...held, recall_alerts: [{ ...alert, status: "dismissed", dismiss_reason: "Checked packs; lot is absent" }] }] }));
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  renderApp("/approvals");
  await user.click(await screen.findByRole("button", { name: "Dismiss recall after checking packs" }));
  const confirm = screen.getByRole("button", { name: /I checked the packs/ });
  expect(confirm).toBeDisabled();
  expect(fetch).toHaveBeenCalledTimes(1);
  await user.type(screen.getByLabelText("Pack-check reason"), "Checked packs; lot is absent");
  await user.click(confirm);
  expect(await screen.findByText(/Recall dismissed for future quotes/)).toBeVisible();
  expect(fetch.mock.calls[1][0]).toBe("/api/v1/kitchens/demo-kitchen/recalls/recall1/dismiss");
  expect(JSON.parse(fetch.mock.calls[1][1].body)).toEqual({ reason: "Checked packs; lot is absent" });
  expect(screen.queryByRole("button", { name: /Approve .*149/ })).toBeNull();
  expect(screen.getByText(/already held basket stays blocked/)).toBeVisible();
});

it("shows a recall hold, lot and pending replacement without an approval action on the original", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ proposals: [{ ...row, status: "BLOCKED_BY_RECALL",
    replacement_proposal_id: "replacement1", recall_alerts: [{ product_id: "462775", match: "possible",
      recall: { url: "https://www.ruokavirasto.fi/notice", title: "Recorded recall", lot: "Lot 2027" } }] }] })));
  renderApp("/approvals");
  expect(await screen.findByText(/BLOCKED_BY_RECALL: 462775/)).toHaveTextContent("Lot 2027");
  expect(screen.getByRole("link", { name: "Official recall notice" })).toHaveAttribute("href", "https://www.ruokavirasto.fi/notice");
  expect(screen.getByRole("link", { name: /Review replacement/ })).toHaveAttribute("href", "#proposal-replacement1");
  expect(screen.queryByRole("button", { name: /Approve .*149/ })).toBeNull();
});

it("loads real proposals and requires explicit confirmation before recording one exact order", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json({ proposals: [row] })).mockResolvedValueOnce(json({ order_id: "order1", expected_total: "149.02" }));
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  renderApp("/approvals");
  await user.click(await screen.findByRole("button", { name: /Approve .*149/ }));
  expect(fetch).toHaveBeenCalledTimes(1);
  await user.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Confirm and record order" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Order recorded: order1");
  expect(screen.getByRole("status")).toHaveTextContent("not submitted to Valio");
  const [url, init] = fetch.mock.calls[1];
  expect(url).toBe("/api/v1/kitchens/demo-kitchen/proposals/p1/approve");
  expect(JSON.parse(init.body)).toEqual({ expected_total: "149.02", idempotency_key: "web-approve-p1-o1" });
  expect(init.headers).not.toHaveProperty("Authorization");
  expect(screen.queryByRole("button", { name: /Approve .*149/ })).toBeNull();
});

it("blocks unknown stock even on an expired offer", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ proposals: [
    { ...row, valid_until: "2000-01-01T00:00:00Z", lines: [{ ...row.lines[0], unknown_stock: true }] },
  ] })));
  renderApp("/approvals");
  for (const button of await screen.findAllByRole("button", { name: /Approve .*149/ })) expect(button).toBeDisabled();
});

it("recovers from an expired changed offer inside the inbox and confirms its new exact total", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json({ proposals: [{ ...row, valid_until: "2000-01-01T00:00:00Z" }] }))
    .mockResolvedValueOnce(new Response(JSON.stringify({ error: { code: "TOTAL_MISMATCH", message: "Price changed; review the new total" } }), { status: 409 }))
    .mockResolvedValueOnce(json({ proposals: [{ ...row, offer_id: "fresh", expected_total: "159.02" }] }))
    .mockResolvedValueOnce(json({ order_id: "order-fresh", expected_total: "159.02" }));
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  renderApp("/approvals");
  await user.click(await screen.findByRole("button", { name: /Approve .*149/ }));
  expect(screen.getByText(/This offer has expired/)).toBeVisible();
  await user.click(screen.getByRole("button", { name: "Confirm and record order" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Price changed");
  expect(screen.queryByRole("status")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Reload proposals" }));
  await user.click(await screen.findByRole("button", { name: /Approve .*159/ }));
  expect(fetch).toHaveBeenCalledTimes(3);
  await user.click(screen.getByRole("button", { name: "Confirm and record order" }));
  expect(await screen.findByRole("status")).toHaveTextContent("order-fresh");
  expect(JSON.parse(fetch.mock.calls[3][1].body)).toEqual({ expected_total: "159.02", idempotency_key: "web-approve-p1-fresh" });
});

it("keeps the decision key after a lost response and never displays an unconfirmed success", async () => {
  const fetch = vi.fn().mockResolvedValueOnce(json({ proposals: [row] })).mockRejectedValueOnce(new TypeError("offline"))
    .mockResolvedValueOnce(json({ order_id: "order1", expected_total: "149.02" }));
  vi.stubGlobal("fetch", fetch);
  const user = userEvent.setup();
  renderApp("/approvals");
  await user.click(await screen.findByRole("button", { name: /Approve .*149/ }));
  await user.click(screen.getByRole("button", { name: "Confirm and record order" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach");
  expect(screen.queryByRole("status")).toBeNull();
  await user.click(screen.getByRole("button", { name: "Confirm and record order" }));
  expect(await screen.findByRole("status")).toHaveTextContent("order1");
  expect(fetch.mock.calls[1][1].body).toBe(fetch.mock.calls[2][1].body);
});

it.each([
  ["approve", /Approve .*149/, "Confirm and record order", { order_id: "order1", expected_total: "149.02" }],
  ["reject", "Reject proposal", "Confirm rejection", { status: "REJECTED", proposal_id: "p1" }],
])("refreshes the waiting-approvals badge after a confirmed %s", async (_, open, confirm, response) => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValueOnce(json({ proposals: [row] })).mockResolvedValueOnce(json(response)));
  const api = createMockApi();
  const listApprovals = vi.spyOn(api, "listApprovals");
  const user = userEvent.setup();
  renderApp("/approvals", api);
  await user.click(await screen.findByRole("button", { name: open }));
  await vi.waitFor(() => expect(listApprovals).toHaveBeenCalled());
  const before = listApprovals.mock.calls.length;
  await user.click(screen.getByRole("button", { name: confirm }));
  await vi.waitFor(() => expect(listApprovals.mock.calls.length).toBeGreaterThan(before));
});
