import { describe, expect, it } from "vitest";

import { mapChainCheck, sha256 } from "@/api/audit-chain";
import { createMockApi } from "@/api/mock";
import { approval } from "@/mocks/milk-case";

describe("sha256", () => {
  it("matches the platform's SHA-256, across block boundaries and for non-ASCII text", async () => {
    for (const text of [
      "",
      "abc",
      "ä€🥛".repeat(7),
      "x".repeat(55),
      "x".repeat(56),
      "x".repeat(64),
      "y".repeat(1000),
    ]) {
      const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
      const expected = Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
      expect(sha256(text)).toBe(expected);
    }
    expect(sha256("abc")).toBe("ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  });
});

describe("mock audit chain", () => {
  it("verifies the untouched chain, also when two readers ask at once", async () => {
    const api = createMockApi();
    const [check, rows] = await Promise.all([api.verifyAuditChain(), api.listAuditChain(5)]);

    expect(check).toMatchObject({ ok: true, length: 8, brokenAt: null, brokenKitchenId: null, kitchenEntries: 8 });
    expect(Number.isNaN(Date.parse(check.checkedAt))).toBe(false);
    expect(rows.map((row) => row.seq)).toEqual([4, 5, 6, 7, 8]);
    expect(rows[0].hash).toMatch(/^[0-9a-f]{64}$/);
    expect(rows[1].prevHash).toBe(rows[0].hash);
  });

  it("gives the same hashes every time", async () => {
    const [first, second] = await Promise.all([createMockApi().listAuditChain(8), createMockApi().listAuditChain(8)]);
    expect(first.map((row) => row.hash)).toEqual(second.map((row) => row.hash));
    expect(first[0].prevHash).toBe("0".repeat(64));
  });

  it("breaks at the tampered line and is whole again after restore", async () => {
    const api = createMockApi();
    const before = await api.listAuditChain(1);

    expect(await api.tamperAuditRow()).toEqual({ seq: 8 });
    const [after] = await api.listAuditChain(1);
    expect(after.event.summary).not.toBe(before[0].event.summary);
    expect(after.hash).toBe(before[0].hash);
    expect(await api.verifyAuditChain()).toMatchObject({
      ok: false,
      length: 7,
      brokenAt: 8,
      brokenKitchenId: "demo-kitchen",
    });
    await expect(api.tamperAuditRow()).rejects.toMatchObject({ code: "ALREADY_TAMPERED" });

    expect(await api.restoreAuditRow()).toEqual({ seq: 8, restored: true });
    expect(await api.verifyAuditChain()).toMatchObject({ ok: true, length: 8, brokenAt: null });
    expect(await api.restoreAuditRow()).toEqual({ seq: null, restored: false });
  });

  it("chains lines written later, and a break before them stays the first break", async () => {
    const api = createMockApi();
    await api.tamperAuditRow();
    await api.reject(approval.id, "Too expensive", "human");

    expect(await api.verifyAuditChain()).toMatchObject({ ok: false, length: 7, brokenAt: 8, kitchenEntries: 9 });
    await api.restoreAuditRow();
    expect(await api.verifyAuditChain()).toMatchObject({ ok: true, length: 9, brokenAt: null });
  });

  it("maps the contract's verify body to the UI type", () => {
    expect(
      mapChainCheck({ ok: false, length: 411, broken_at: 412, broken_kitchen_id: "demo-kitchen", kitchen_entries: 57 }),
    ).toMatchObject({ ok: false, length: 411, brokenAt: 412, brokenKitchenId: "demo-kitchen", kitchenEntries: 57 });
  });
});
