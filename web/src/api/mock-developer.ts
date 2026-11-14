import type { Api, CreatedWebhook, Webhook } from "@/api/types";
import type { AuditEvent } from "@/types";

type DeveloperApi = Pick<Api, "listWebhooks" | "createWebhook" | "testWebhook" | "getGatewayHealth" | "listRecentApiCalls">;
type AuditRecorder = (event: Pick<AuditEvent, "kind" | "actor" | "summary" | "reason">) => void;

const EVENTS = ["proposal.ready", "proposal.approved", "proposal.rejected", "order.placed", "total_mismatch", "recall.alert"];

export function createDeveloperMock(recordAudit: AuditRecorder): DeveloperApi {
  const webhooks: Webhook[] = [
    {
      id: "hook-demo-1",
      url: "https://hooks.example.test/kitchen",
      events: ["proposal.ready", "recall.alert"],
      createdAt: "2026-11-14T08:00:00+00:00",
      createdBy: "buyer@demo.kitchen",
    },
  ];
  let nextId = 2;
  return {
    async listWebhooks() {
      return { webhooks: structuredClone(webhooks), events: [...EVENTS] };
    },
    async createWebhook(input, actor) {
      const created: CreatedWebhook = {
        id: `hook-demo-${nextId++}`,
        url: input.url,
        events: [...input.events],
        createdAt: new Date().toISOString(),
        createdBy: actor === "human" ? "buyer@demo.kitchen" : actor,
        secret: `whsec_demo_${String(nextId).padStart(4, "0")}`,
      };
      const { secret: _secret, ...hook } = created;
      webhooks.push(hook);
      recordAudit({ kind: "other", actor, summary: "Webhook created", reason: `${created.url}: ${created.events.join(", ")}` });
      return structuredClone(created);
    },
    async testWebhook(id) {
      const hook = webhooks.find((row) => row.id === id);
      return {
        id: `delivery-${id}`,
        event: "ping",
        at: new Date().toISOString(),
        attempts: 1,
        status: hook ? 200 : null,
        ok: Boolean(hook),
        error: hook ? null : "WEBHOOK_NOT_FOUND",
      };
    },
    async getGatewayHealth() {
      return { status: "not connected (sample data)", valioMode: "unknown" };
    },
    async listRecentApiCalls() {
      return [
        { id: "call-1", method: "GET", path: "/v1/kitchens/demo-kitchen/orders", status: 200, at: "2026-11-14T09:58:00+00:00" },
        { id: "call-2", method: "POST", path: "/v1/kitchens/demo-kitchen/proposals", status: 201, at: "2026-11-14T09:57:00+00:00" },
        { id: "call-3", method: "GET", path: "/health", status: 200, at: "2026-11-14T09:56:00+00:00" },
      ];
    },
  };
}
