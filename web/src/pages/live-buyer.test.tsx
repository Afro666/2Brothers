import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "@/test/render";

const ready = {
  proposal_id: "live-1",
  status: "READY",
  expected_total: "149.02",
  total_ex_vat: "131.07",
  buyer_model: "nemotron-3.5-super-vl",
  lines: [
    { product_id: "462775", quantity: "51", unit: "ST", why: "51 units sized by the engine", unknown_stock: false },
  ],
};

const name = "Arla Milkdrink 1L lactose free fat free UHT Suomesta";
const chosen = `51 ST of 462775 ${name}, EUR 131.07 ex VAT: 51 ST of ${name} = 51 L, confirmed in stock.`;
const shortfall = "949 L of the request cannot be covered for this date.";
const summary = {
  asked: 'Asked: "1,000 L milk by Monday" (1000 L for 2026-11-16).',
  searched: "Checked 1 product(s) with Valio prices and stock for 2026-11-16: 462775.",
  chosen: [chosen],
  text: `Asked: "1,000 L milk by Monday" (1000 L for 2026-11-16).\nChosen: ${chosen}\n${shortfall}`,
};

async function fill() {
  const user = userEvent.setup();
  renderApp("/requests");
  await user.type(await screen.findByLabelText("What do you need?"), "51 L milk by Monday");
  await user.type(screen.getByLabelText("Needed by"), "2026-11-16");
  await user.click(screen.getByRole("button", { name: "Ask the agent" }));
  return user;
}

describe("live Buyer request page", () => {
  beforeEach(() => vi.stubEnv("VITE_LIVE_BUYER", "true"));
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("shows engine-backed chef options as preferences without applying a mutation", async () => {
    const fetch = vi.fn(
      async () =>
        new Response(
          JSON.stringify({
            ...ready,
            substitute_options: [
              {
                tier: "better",
                expected_total: "1329.04",
                why: "Supplier-linked substitute sized by the engine.",
                stock_confirmed: false,
                allergen_data_known: false,
                requires_chef_approval: true,
                lines: ready.lines,
              },
            ],
          }),
        ),
    );
    vi.stubGlobal("fetch", fetch);
    const user = await fill();
    await user.click(await screen.findByRole("button", { name: "Prefer better" }));
    expect(screen.getByText(/This preference has not changed or approved an order/)).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("sends the request to the real gateway without a browser key and shows exact returned figures", async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(ready)));
    vi.stubGlobal("fetch", fetch);
    await fill();
    expect(await screen.findByText("Proposal ready for human review")).toBeVisible();
    expect(screen.getByText(/131.07.*149.02/)).toBeVisible();
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe("/api/v1/kitchens/demo-kitchen/proposals");
    expect(init.headers).not.toHaveProperty("Authorization");
    expect(JSON.parse(init.body as string)).toMatchObject({
      text: "51 L milk by Monday",
      requested_date: "2026-11-16",
    });
    expect(JSON.parse(init.body as string).idempotency_key).toBeTruthy();
    expect(screen.getByText(/No order has been placed/)).toBeVisible();
  });

  it("keeps the same request key after an ambiguous network error", async () => {
    const fetch = vi
      .fn()
      .mockRejectedValueOnce(new TypeError("offline"))
      .mockResolvedValue(new Response(JSON.stringify(ready)));
    vi.stubGlobal("fetch", fetch);
    const user = await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the gateway");
    await user.click(screen.getByRole("button", { name: "Ask the agent" }));
    await screen.findByText("Proposal ready for human review");
    const keys = fetch.mock.calls.map((call) => JSON.parse(call[1].body).idempotency_key);
    expect(keys[0]).toBe(keys[1]);
  });

  it("shows unknown stock and does not link the live proposal to the mock inbox", async () => {
    vi.stubGlobal(
      "fetch",
      async () => new Response(JSON.stringify({ ...ready, lines: [{ ...ready.lines[0], unknown_stock: true }] })),
    );
    await fill();
    expect(await screen.findByText(/Waiting for supplier stock confirmation/)).toBeVisible();
    expect(screen.queryByRole("link", { name: /Review it in Approvals/ })).toBeNull();
  });

  it("says in plain words why the basket was chosen and what the guards said", async () => {
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(
          JSON.stringify({
            ...ready,
            decision_summary: summary,
            mandate: { verdict: "NEEDS_APPROVAL", reasons: [shortfall], reason_codes: ["PARTIAL_STOCK"], warnings: [] },
          }),
        ),
    );
    await fill();
    const why = await screen.findByRole("region", { name: "Why this basket" });
    // The summary is shown verbatim, line breaks included.
    expect(within(why).getByText((_, element) => element?.textContent === summary.text)).toBeVisible();
    expect(within(why).getByText("What was asked").nextSibling).toHaveTextContent(summary.asked);
    expect(within(why).getByText("What was searched").nextSibling).toHaveTextContent(summary.searched);
    expect(within(why).getByText("What was chosen").nextSibling).toHaveTextContent(chosen);
    const guards = screen.getByRole("region", { name: "What the guards said" });
    expect(within(guards).getByText("Needs a person’s approval")).toBeVisible();
    expect(within(guards).getByRole("listitem")).toHaveTextContent(shortfall);
    expect(screen.getByText("Proposed by the Buyer agent (Nemotron 3.5 Super VL)")).toBeVisible();
    expect(screen.getByText(`51 ST · ${name} (462775)`)).toBeVisible();
  });

  it("shows unknown, not a blank or a crash, when the summary and the mandate are absent", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ...ready, buyer_model: undefined })));
    await fill();
    expect(await screen.findByRole("region", { name: "Why this basket" })).toHaveTextContent(/unknown/);
    const guards = screen.getByRole("region", { name: "What the guards said" });
    expect(guards).toHaveTextContent("Verdict: unknown");
    expect(guards).toHaveTextContent("Reasons: unknown");
    expect(screen.getByText("Proposed by the Buyer agent")).toBeVisible();
    expect(screen.getByText("51 ST · 462775")).toBeVisible();
  });

  it("does not credit the Buyer model for a proposal the gateway parser made", async () => {
    vi.stubGlobal(
      "fetch",
      async () =>
        new Response(
          JSON.stringify({
            ...ready,
            buyer_model: undefined,
            request: { made_by: "parser" },
            mandate: { verdict: "NEEDS_APPROVAL", reasons: [] },
          }),
        ),
    );
    await fill();
    expect(await screen.findByText(/Proposed by the gateway’s request parser/)).toBeVisible();
    expect(screen.getByText("No reasons given.")).toBeVisible();
  });
});
