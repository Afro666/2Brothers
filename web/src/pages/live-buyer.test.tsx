import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderApp } from "@/test/render";

const ready = { proposal_id: 'live-1', status: 'READY', expected_total: '149.02', total_ex_vat: '131.07',
  buyer_model: 'nemotron-3.5-super-vl', lines: [{ product_id: '462775', quantity: '51', unit: 'ST',
    why: '51 units sized by the engine', unknown_stock: false }] };

async function fill() {
  const user = userEvent.setup();
  renderApp('/requests');
  await user.type(await screen.findByLabelText('What do you need?'), '51 L milk by Monday');
  await user.type(screen.getByLabelText('Needed by'), '2026-11-16');
  await user.click(screen.getByRole('button', { name: 'Ask the agent' }));
  return user;
}

describe('live Buyer request page', () => {
  beforeEach(() => vi.stubEnv('VITE_LIVE_BUYER', 'true'));
  afterEach(() => { vi.unstubAllGlobals(); vi.unstubAllEnvs(); });

  it('sends the request to the real gateway without a browser key and shows exact returned figures', async () => {
    const fetch = vi.fn(async () => new Response(JSON.stringify(ready)));
    vi.stubGlobal('fetch', fetch);
    await fill();
    expect(await screen.findByText('Proposal ready for human review')).toBeVisible();
    expect(screen.getByText(/131.07.*149.02/)).toBeVisible();
    const [url, init] = fetch.mock.calls[0] as unknown as [string, RequestInit];
    expect(url).toBe('/api/v1/kitchens/demo-kitchen/proposals');
    expect(init.headers).not.toHaveProperty('Authorization');
    expect(JSON.parse(init.body as string)).toMatchObject({ text: '51 L milk by Monday', requested_date: '2026-11-16' });
    expect(JSON.parse(init.body as string).idempotency_key).toBeTruthy();
    expect(screen.getByText(/No order has been placed/)).toBeVisible();
  });

  it('keeps the same request key after an ambiguous network error', async () => {
    const fetch = vi.fn().mockRejectedValueOnce(new TypeError('offline')).mockResolvedValue(new Response(JSON.stringify(ready)));
    vi.stubGlobal('fetch', fetch);
    const user = await fill();
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not reach the gateway');
    await user.click(screen.getByRole('button', { name: 'Ask the agent' }));
    await screen.findByText('Proposal ready for human review');
    const keys = fetch.mock.calls.map((call) => JSON.parse(call[1].body).idempotency_key);
    expect(keys[0]).toBe(keys[1]);
  });

  it('shows unknown stock and does not link the live proposal to the mock inbox', async () => {
    vi.stubGlobal('fetch', async () => new Response(JSON.stringify({ ...ready, lines: [{...ready.lines[0], unknown_stock: true}] })));
    await fill();
    expect(await screen.findByText(/Waiting for supplier stock confirmation/)).toBeVisible();
    expect(screen.queryByRole('link', { name: /Review it in Approvals/ })).toBeNull();
  });
});
