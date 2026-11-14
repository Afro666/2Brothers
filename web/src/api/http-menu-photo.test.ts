import { afterEach, describe, expect, it, vi } from "vitest";

import { createHttpApi } from "@/api/http";
import { mapMenuPhoto } from "@/api/http-menu-photo";

const MATCHED = {
  day: "2026-11-16",
  dish: "Salmon soup",
  covers: 120,
  recipe_id: "env-salmon_soup",
  recipe_name: "Salmon soup",
  status: "MATCHED",
  in_proposal: true,
};
const UNKNOWN = {
  day: "2026-11-20",
  dish: "Reindeer stew",
  covers: 80,
  recipe_id: null,
  recipe_name: null,
  status: "NOT_KNOWN",
  in_proposal: false,
};
const ANSWER = {
  model: "nemotron-3.5-super-vl",
  duration_ms: 6120,
  from: "2026-11-16",
  to: "2026-11-22",
  dishes: [MATCHED, UNKNOWN],
  proposal: { proposal_id: "prop-1", status: "READY" },
  no_proposal_reason: null,
};

function gateway(answer: () => unknown) {
  const calls: { route: string; user: string | undefined; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal("fetch", async (url: string, init: RequestInit = {}) => {
    calls.push({
      route: `${init.method ?? "GET"} ${url}`,
      user: (init.headers as Record<string, string>)["X-User"],
      body: init.body ? JSON.parse(init.body as string) : null,
    });
    const body = answer();
    return body instanceof Response ? body : new Response(JSON.stringify(body));
  });
  return calls;
}

afterEach(() => vi.unstubAllGlobals());

describe("Plan from a menu photo on the real gateway", () => {
  it("posts the photo and the week as JSON and maps the dishes", async () => {
    const calls = gateway(() => ANSWER);
    const api = createHttpApi("/api");
    expect(api.live!.has("readMenuPhoto")).toBe(true);
    const read = await api.readMenuPhoto(
      new Blob([new Uint8Array([0xff, 0xd8, 0xff, 0xe0])]),
      { from: "2026-11-16", to: "2026-11-22", requestedDate: "2026-11-16" },
      "chef",
    );
    expect(calls).toHaveLength(1);
    expect(calls[0].route).toBe("POST /api/v1/kitchens/demo-kitchen/menu-photo");
    expect(calls[0].user).toBe("chef");
    expect(calls[0].body).toMatchObject({
      image_base64: "/9j/4A==",
      from: "2026-11-16",
      to: "2026-11-22",
      requested_date: "2026-11-16",
    });
    expect(calls[0].body?.idempotency_key).toMatch(/^web-menu-photo:[0-9a-f]+$/);
    expect(read).toEqual({
      model: "nemotron-3.5-super-vl",
      durationMs: 6120,
      from: "2026-11-16",
      to: "2026-11-22",
      dishes: [
        {
          day: "2026-11-16",
          dish: "Salmon soup",
          covers: 120,
          recipeId: "env-salmon_soup",
          recipeName: "Salmon soup",
          status: "MATCHED",
          inProposal: true,
        },
        {
          day: "2026-11-20",
          dish: "Reindeer stew",
          covers: 80,
          recipeId: null,
          recipeName: null,
          status: "NOT_KNOWN",
          inProposal: false,
        },
      ],
      proposal: { id: "prop-1", status: "READY" },
      noProposalReason: null,
    });
  });

  it("never gives a not-known dish a recipe or a place in the proposal", () => {
    const read = mapMenuPhoto({ ...ANSWER, dishes: [{ ...UNKNOWN, recipe_id: "env-burger", in_proposal: true }] });
    expect(read.dishes[0]).toMatchObject({ recipeId: null, recipeName: null, inProposal: false });
  });

  it("keeps unknown covers and days unknown, never a number", () => {
    const read = mapMenuPhoto({ ...ANSWER, dishes: [{ ...MATCHED, covers: "lots", day: "Monday" }] });
    expect(read.dishes[0]).toMatchObject({ covers: null, day: null });
  });

  it("refuses an answer it cannot trust", () => {
    expect(() => mapMenuPhoto({ ...ANSWER, dishes: [{ ...MATCHED, recipe_id: null }] })).toThrow(/unexpected shape/);
    expect(() => mapMenuPhoto({ ...ANSWER, dishes: [{ ...MATCHED, status: "GUESSED" }] })).toThrow(/unexpected shape/);
    expect(() => mapMenuPhoto({ ...ANSWER, proposal: { status: "READY" } })).toThrow(/unexpected shape/);
    expect(() => mapMenuPhoto({ ...ANSWER, model: "" })).toThrow(/unexpected shape/);
  });

  it("says why no proposal was made", () => {
    const read = mapMenuPhoto({ ...ANSWER, proposal: null, no_proposal_reason: "NOTHING_NEEDED" });
    expect(read.proposal).toBeNull();
    expect(read.noProposalReason).toBe("NOTHING_NEEDED");
  });

  it("passes the error on, with the dishes read for NOTHING_MATCHED", async () => {
    gateway(
      () =>
        new Response(
          JSON.stringify({ error: { code: "NOTHING_MATCHED", message: "no dish matched", dishes: [UNKNOWN] } }),
          { status: 422 },
        ),
    );
    await expect(
      createHttpApi("/api").readMenuPhoto(new Blob(["x"]), { from: "2026-11-16", to: "2026-11-22" }, "human"),
    ).rejects.toMatchObject({
      code: "NOTHING_MATCHED",
      status: 422,
      details: { dishes: [{ dish: "Reindeer stew", status: "NOT_KNOWN", recipeId: null }] },
    });
  });

  it("passes the gateway's vision error code on", async () => {
    gateway(
      () =>
        new Response(JSON.stringify({ error: { code: "VISION_UNAVAILABLE", message: "model down" } }), { status: 503 }),
    );
    await expect(
      createHttpApi("/api").readMenuPhoto(new Blob(["x"]), { from: "2026-11-16", to: "2026-11-22" }, "human"),
    ).rejects.toMatchObject({ code: "VISION_UNAVAILABLE", status: 503 });
  });

  it("keeps a missing timing unknown, not zero", () => {
    const { duration_ms: _timing, ...untimed } = ANSWER;
    expect(mapMenuPhoto(untimed).durationMs).toBeNull();
  });
});
