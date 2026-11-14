import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";

const K = "/api/v1/kitchens/demo-kitchen";
type Handler = (body: Record<string, unknown>) => unknown;

/** A fake gateway: `"POST /path"` -> the JSON it answers. Returns the calls it received. */
function gateway(routes: Record<string, Handler>) {
  const calls: { route: string; body: Record<string, unknown> }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    const route = `${init.method ?? "GET"} ${url}`;
    const body = init.body ? JSON.parse(init.body as string) : {};
    calls.push({ route, body });
    const answer = routes[route]
      ? routes[route](body)
      : new Response(JSON.stringify({ error: { code: "NO_ROUTE", message: route } }), { status: 404 });
    return answer instanceof Response ? answer : new Response(JSON.stringify(answer));
  });
  return calls;
}

const HASH_A = "a".repeat(64);
const HASH_B = "b".repeat(64);
const entry = {
  seq: 412,
  prev_hash: HASH_A,
  hash: HASH_B,
  event: { event_id: "e-412", kind: "order_placed", actor: "aron", at: "2026-11-14T02:00:00+00:00" },
};

afterEach(() => vi.unstubAllGlobals());

describe("Trust page on the real gateway", () => {
  it("marks the four methods as live", () => {
    gateway({});
    const live = createHttpApi("/api").live!;
    for (const name of ["listAuditChain", "verifyAuditChain", "tamperAuditRow", "restoreAuditRow"] as const) {
      expect(live.has(name)).toBe(true);
    }
  });

  it("verifies the chain and maps the answer", async () => {
    gateway({
      [`GET ${K}/audit/verify`]: () => ({
        ok: false,
        length: 637,
        broken_at: 412,
        broken_kitchen_id: "demo-kitchen",
        kitchen_entries: 605,
      }),
    });
    const check = await createHttpApi("/api").verifyAuditChain();
    expect(check).toMatchObject({ ok: false, length: 637, brokenAt: 412, brokenKitchenId: "demo-kitchen" });
    expect(check.kitchenEntries).toBe(605);
  });

  it("lists the newest lines with their hashes", async () => {
    const calls = gateway({ [`GET ${K}/audit/chain?limit=5`]: () => ({ entries: [entry] }) });
    const [row] = await createHttpApi("/api").listAuditChain(5);
    expect(row).toMatchObject({ seq: 412, prevHash: HASH_A, hash: HASH_B });
    expect(row.event.id).toBe("e-412");
    expect(calls.map((call) => call.route)).toEqual([`GET ${K}/audit/chain?limit=5`]);
  });

  it("tampers and restores with a new key per click", async () => {
    const calls = gateway({
      [`POST ${K}/audit/demo-tamper`]: () => ({ seq: 412, tampered: true }),
      [`POST ${K}/audit/demo-restore`]: () => ({ seq: 412, restored: true }),
    });
    const api = createHttpApi("/api");
    expect(await api.tamperAuditRow()).toEqual({ seq: 412 });
    expect(await api.tamperAuditRow()).toEqual({ seq: 412 });
    expect(await api.restoreAuditRow()).toEqual({ seq: 412, restored: true });
    const keys = calls.map((call) => call.body.idempotency_key);
    expect(keys.every((key) => typeof key === "string" && key.length === 32)).toBe(true);
    expect(new Set(keys).size).toBe(3);
  });

  it("says nothing was tampered, and passes a refusal on with its code", async () => {
    gateway({
      [`POST ${K}/audit/demo-restore`]: () => ({ seq: null, restored: false }),
      [`POST ${K}/audit/demo-tamper`]: () =>
        new Response(JSON.stringify({ error: { code: "ALREADY_TAMPERED", message: "restore it first" } }), {
          status: 409,
        }),
    });
    const api = createHttpApi("/api");
    expect(await api.restoreAuditRow()).toEqual({ seq: null, restored: false });
    await expect(api.tamperAuditRow()).rejects.toMatchObject({ code: "ALREADY_TAMPERED" });
  });

  it("refuses a body in the wrong shape instead of showing a guess", async () => {
    gateway({
      [`GET ${K}/audit/verify`]: () => ({ ok: "yes", length: 3 }),
      [`GET ${K}/audit/chain?limit=5`]: () => ({ entries: [{ ...entry, hash: null }] }),
    });
    const api = createHttpApi("/api");
    await expect(api.verifyAuditChain()).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
    await expect(api.listAuditChain(5)).rejects.toMatchObject({ code: "INVALID_RESPONSE" });
  });
});
