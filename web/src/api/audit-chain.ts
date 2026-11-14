import type { AuditChainCheck, AuditChainRow } from "@/api/types";
import type { AuditEvent } from "@/types";

/** The kitchen this web app shows; the gateway's paths are under it. */
export const KITCHEN_ID: string = import.meta.env.VITE_GATEWAY_KITCHEN_ID || "demo-kitchen";

/** The `prevHash` of the first line, as in store/audit.py. */
export const GENESIS = "0".repeat(64);

const PRIMES: number[] = [];
for (let n = 2; PRIMES.length < 64; n++) if (PRIMES.every((prime) => n % prime)) PRIMES.push(n);
const fraction = (value: number) => ((value - Math.floor(value)) * 2 ** 32) >>> 0;
const K = PRIMES.map((prime) => fraction(Math.cbrt(prime)));
const rotr = (value: number, bits: number) => (value >>> bits) | (value << (32 - bits));

/**
 * SHA-256 as hex. Written out because `crypto.subtle` does not exist on a plain-HTTP page,
 * and the demo site can be one (`SITE_ADDRESS` in web/Caddyfile).
 */
export function sha256(text: string): string {
  const bytes = [...new TextEncoder().encode(text)];
  const bits = bytes.length * 8;
  bytes.push(0x80);
  while (bytes.length % 64 !== 56) bytes.push(0);
  // shortcut: the length is written as 32 bits, enough for 512 MB; an audit line is far smaller.
  bytes.push(0, 0, 0, 0, bits >>> 24, (bits >>> 16) & 255, (bits >>> 8) & 255, bits & 255);
  const state = PRIMES.slice(0, 8).map((prime) => fraction(Math.sqrt(prime)));
  for (let offset = 0; offset < bytes.length; offset += 64) {
    const w: number[] = [];
    for (let i = 0; i < 64; i++) {
      if (i < 16) {
        const at = offset + i * 4;
        w[i] = (bytes[at] << 24) | (bytes[at + 1] << 16) | (bytes[at + 2] << 8) | bytes[at + 3];
      } else {
        const s0 = rotr(w[i - 15], 7) ^ rotr(w[i - 15], 18) ^ (w[i - 15] >>> 3);
        const s1 = rotr(w[i - 2], 17) ^ rotr(w[i - 2], 19) ^ (w[i - 2] >>> 10);
        w[i] = (w[i - 16] + s0 + w[i - 7] + s1) | 0;
      }
    }
    let [a, b, c, d, e, f, g, h] = state;
    for (let i = 0; i < 64; i++) {
      const t1 = (h + (rotr(e, 6) ^ rotr(e, 11) ^ rotr(e, 25)) + ((e & f) ^ (~e & g)) + K[i] + w[i]) | 0;
      const t2 = ((rotr(a, 2) ^ rotr(a, 13) ^ rotr(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) | 0;
      [a, b, c, d, e, f, g, h] = [(t1 + t2) | 0, a, b, c, (d + t1) | 0, e, f, g];
    }
    [a, b, c, d, e, f, g, h].forEach((value, i) => {
      state[i] = (state[i] + value) | 0;
    });
  }
  return state.map((value) => (value >>> 0).toString(16).padStart(8, "0")).join("");
}

/** The hash of one line: its place, the hash before it and everything the line says. */
export function rowHash(seq: number, prevHash: string, event: AuditEvent): string {
  return sha256(
    JSON.stringify([
      seq,
      prevHash,
      event.id,
      event.at,
      event.kind,
      event.actor,
      event.summary,
      event.reason,
      event.orderId ?? null,
    ]),
  );
}

/** The same rule and result as `verify_entries` in store/audit.py; `rows` is the whole chain in order. */
export function verifyRows(rows: AuditChainRow[]): { ok: boolean; length: number; broken_at: number | null } {
  let prev = GENESIS;
  for (const [index, row] of rows.entries()) {
    if (row.seq !== index + 1 || row.prevHash !== prev || row.hash !== rowHash(row.seq, row.prevHash, row.event)) {
      return { ok: false, length: index, broken_at: row.seq };
    }
    prev = row.hash;
  }
  return { ok: true, length: rows.length, broken_at: null };
}

/** The contract's `GET /audit/verify` body (snake_case) as the UI type. */
export function mapChainCheck(body: {
  ok: boolean;
  length: number;
  broken_at: number | null;
  broken_kitchen_id: string | null;
  kitchen_entries: number;
}): AuditChainCheck {
  return {
    ok: body.ok,
    length: body.length,
    brokenAt: body.broken_at,
    brokenKitchenId: body.broken_kitchen_id,
    kitchenEntries: body.kitchen_entries,
    checkedAt: new Date().toISOString(),
  };
}
