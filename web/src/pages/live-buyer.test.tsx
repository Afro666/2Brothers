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

const rejected = {
  proposal_id: "live-rejected-1",
  status: "REJECTED",
  expected_total: "0.00",
  total_ex_vat: "0.00",
  request: { made_by: "parser" },
  decision_summary: {
    asked: 'Asked: "1,000 L lactose-free milk by Monday" (1000 L for 2026-11-16).',
    searched: "Checked 3 product(s) with Valio prices and stock for 2026-11-16: 462775, 462921, 463335.",
    chosen: [],
    left_out: [
      "462775 left out: the supplier cut-off has passed for 2026-11-16.",
      "462921 left out: pack size is unknown.",
      "463335 left out: stock is unknown.",
    ],
    decide: ["Nothing can be ordered: no line passed the checks."],
    text: 'Asked: "1,000 L lactose-free milk by Monday" (1000 L for 2026-11-16).\nChosen: nothing.\n462775 left out: the supplier cut-off has passed for 2026-11-16.\n462921 left out: pack size is unknown.\n463335 left out: stock is unknown.\nTo decide: Nothing can be ordered: no line passed the checks.',
  },
  mandate: { verdict: "REFUSED", reasons: ["No line passed the checks."] },
  lines: [],
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
    expect(screen.getByText("Stock not confirmed")).toBeVisible();
    expect(screen.getByText("Allergen data unknown")).toBeVisible();
    expect(screen.getByText(/This preference has not changed or approved an order/)).toBeVisible();
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it("rejects a substitute option with a malformed line", async () => {
    const option = {
      tier: "good",
      expected_total: "100.00",
      why: "Cheaper substitute.",
      stock_confirmed: true,
      allergen_data_known: true,
      requires_chef_approval: true,
      lines: [{ product_id: "462775" }],
    };
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify({ ...ready, substitute_options: [option] })));
    await fill();
    expect(await screen.findByRole("alert")).toBeVisible();
    expect(screen.queryByText("Proposal ready for human review")).toBeNull();
    expect(screen.queryByText(/undefined/)).toBeNull();
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
    expect(screen.queryByRole("link", { name: /Review it (in|under) / })).toBeNull();
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

  it("explains why a rejected proposal has no orderable lines", async () => {
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(rejected)));
    await fill();
    const blocked = await screen.findByRole("status", { name: "Nothing can be ordered" });
    expect(blocked).toHaveTextContent("Nothing can be ordered");
    expect(within(blocked).getByText(rejected.decision_summary.asked)).toBeVisible();
    for (const reason of rejected.decision_summary.left_out) {
      expect(within(blocked).getByText(reason)).toBeVisible();
    }
    expect(screen.getByRole("region", { name: "What the guards said" })).toHaveTextContent("No line passed the checks.");
    expect(screen.getByText("Made by the fallback parser because the Buyer agent was not available")).toBeVisible();
    expect(screen.queryByText("Proposal ready for human review")).toBeNull();
    expect(screen.queryByRole("link", { name: "Open live approval inbox" })).toBeNull();
  });

  it("shows a request the allergen rule refused as one plain sentence, with the products folded once", async () => {
    const message =
      'This kitchen excludes peanuts, so "peanut butter" cannot be ordered: every best match contains peanuts. No other kind of product is proposed in its place.';
    const products = [
      "100001 left out: ALLERGEN_RULE: the kitchen excludes AN, AP, AS, SA, SC, ST",
      "100002 left out: ALLERGEN_RULE: the kitchen excludes AN, AP, AS, SA, SC, ST",
    ];
    const refused = {
      ...rejected,
      request: { made_by: "parser", refusal: { code: "ALLERGEN_RULE", allergens: ["peanuts"], message } },
      decision_summary: {
        asked: 'Asked: "15 kg peanut butter".',
        chosen: [],
        left_out: products,
        text: ['Asked: "15 kg peanut butter".', "Chosen: nothing.", ...products].join("\n"),
      },
      mandate: { verdict: "REFUSED", reason_codes: ["ALLERGEN_RULE"], reasons: [message, ...products] },
    };
    vi.stubGlobal("fetch", async () => new Response(JSON.stringify(refused)));
    await fill();
    const blocked = await screen.findByRole("status", { name: "Nothing can be ordered" });
    expect(within(blocked).getByText(message)).toBeVisible();
    expect(screen.getByText("Refused by the kitchen’s allergen rule")).toBeVisible();
    expect(screen.queryByText(/fallback parser/)).toBeNull();
    const folded = within(blocked).getByText("Products that were left out").closest("details");
    expect(folded).not.toHaveAttribute("open");
    for (const line of products) expect(screen.getAllByText(line, { exact: false })).toHaveLength(1);
    expect(screen.queryByRole("region", { name: "Why this basket" })).toBeNull();
    expect(screen.getByRole("region", { name: "What the guards said" })).toHaveTextContent("Refused");
  });

  it.each([
    ["READY", []],
    ["REJECTED", ready.lines],
  ])("keeps the current error for a malformed %s proposal", async (status, lines) => {
    vi.stubGlobal(
      "fetch",
      async () => new Response(JSON.stringify({ ...ready, status, lines })),
    );
    await fill();
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "The Buyer did not return a ready proposal. Check the existing request before trying again.",
    );
    expect(screen.queryByRole("status", { name: "Nothing can be ordered" })).toBeNull();
  });
});
