import { mapChainCheck } from "@/api/audit-chain";
import { type Json, mapAudit, object, rows, text } from "@/api/gateway-map";
import type { Api, AuditChainRow } from "@/api/types";
import { ApiError } from "@/api/types";

/** The gateway request of api/http.ts: a path under the base URL, the parsed JSON back. */
type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;

type TrustApi = Pick<Api, "listAuditChain" | "verifyAuditChain" | "tamperAuditRow" | "restoreAuditRow">;

/** A new key per click: the gateway answers the stored result again for a repeated key. */
function key(): string {
  // getRandomValues, not randomUUID: it also works on a plain-HTTP address.
  return Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) => value.toString(16).padStart(2, "0")).join(
    "",
  );
}

function whole(value: unknown, what: string): number {
  if (typeof value !== "number" || !Number.isInteger(value)) {
    throw new ApiError("INVALID_RESPONSE", `The gateway sent ${what} in an unexpected shape.`);
  }
  return value;
}

/**
 * The Trust page against the real gateway (gateway/trust_routes.py): the audit hash chain
 * stored in MongoDB Atlas, its verification, and the tamper demo. `kitchen` is
 * `/v1/kitchens/{id}`. Contract: docs/contract.md, "Trust".
 */
export function createTrustHttp(call: GatewayCall, kitchen: string): TrustApi {
  const send = (path: string) => call(path, { method: "POST", body: JSON.stringify({ idempotency_key: key() }) });
  return {
    async listAuditChain(limit) {
      const entries = rows(await call(`${kitchen}/audit/chain?limit=${encodeURIComponent(limit)}`), "entries");
      return entries.map(
        (entry): AuditChainRow => ({
          seq: whole(entry.seq, "an audit line number"),
          event: mapAudit([object(entry.event, "an audit line")])[0],
          prevHash: text(entry.prev_hash, "a previous hash"),
          hash: text(entry.hash, "a hash"),
        }),
      );
    },
    async verifyAuditChain() {
      const body = object(await call(`${kitchen}/audit/verify`), "the chain check");
      if (typeof body.ok !== "boolean") throw new ApiError("INVALID_RESPONSE", "The chain check has no answer.");
      return mapChainCheck({
        ok: body.ok,
        length: whole(body.length, "the chain length"),
        broken_at: body.broken_at == null ? null : whole(body.broken_at, "the broken line"),
        broken_kitchen_id: typeof body.broken_kitchen_id === "string" ? body.broken_kitchen_id : null,
        kitchen_entries: whole(body.kitchen_entries, "the kitchen's line count"),
      });
    },
    async tamperAuditRow() {
      const body = object(await send(`${kitchen}/audit/demo-tamper`), "the tamper answer") as Json;
      return { seq: whole(body.seq, "the tampered line") };
    },
    async restoreAuditRow() {
      const body = object(await send(`${kitchen}/audit/demo-restore`), "the restore answer") as Json;
      return { seq: body.seq == null ? null : whole(body.seq, "the restored line"), restored: body.restored === true };
    },
  };
}
