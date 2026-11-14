import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { renderApp } from "@/test/render";

const row = {
  proposal_id: "p1", offer_id: "o1", status: "READY", valid_until: "2099-01-01T00:00:00Z",
  expected_total: "149.02", total_ex_vat: "131.07",
  lines: [{ product_id: "462775", quantity: "51", unit: "ST", why: "Measured stock", unknown_stock: false }],
};
beforeEach(() => vi.stubEnv("VITE_LIVE_BUYER", "true"));
afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });
const json = (body: unknown) => new Response(JSON.stringify(body));

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

it("blocks unknown stock and expired offers", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ proposals: [
    { ...row, lines: [{ ...row.lines[0], unknown_stock: true }] },
    { ...row, proposal_id: "expired", valid_until: "2000-01-01T00:00:00Z" },
  ] })));
  renderApp("/approvals");
  for (const button of await screen.findAllByRole("button", { name: /Approve .*149/ })) expect(button).toBeDisabled();
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
