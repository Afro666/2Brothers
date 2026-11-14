import { ApiError, type Api, type KitchenDeletionRequest } from "@/api/types";
import type { AuditEvent } from "@/types";

type AuditRecorder = (event: Pick<AuditEvent, "kind" | "actor" | "summary" | "reason">) => void;

export function createPrivacyMock(recordAudit: AuditRecorder): Pick<Api, "requestKitchenDeletion"> {
  let nextId = 1;
  return {
    async requestKitchenDeletion(confirmation, actor): Promise<KitchenDeletionRequest> {
      if (confirmation !== "DELETE") throw new ApiError("INVALID", "Type DELETE to confirm the request.");
      const request = { id: `deletion-request-${nextId++}`, requestedAt: new Date().toISOString(), status: "requested" as const };
      recordAudit({ kind: "other", actor, summary: "Kitchen deletion requested", reason: `${request.id}; no kitchen data was deleted` });
      return request;
    },
  };
}
