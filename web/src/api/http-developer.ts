import { type Json, object } from "@/api/gateway-map";
import { ApiError, type Api, type Webhook, type WebhookDelivery } from "@/api/types";

type GatewayCall = (path: string, init?: RequestInit) => Promise<unknown>;
type DeveloperHttp = Pick<Api, "listWebhooks" | "createWebhook" | "testWebhook" | "getGatewayHealth">;

function nullableText(value: unknown): string | null {
  return typeof value === "string" && value ? value : null;
}

export function mapWebhook(value: unknown): Webhook {
  const row = object(value, "webhook");
  if (typeof row.webhook_id !== "string" || typeof row.url !== "string" || !Array.isArray(row.events) || !row.events.every((event) => typeof event === "string")) {
    throw new ApiError("INVALID_RESPONSE", "The gateway sent an incomplete webhook.");
  }
  return {
    id: row.webhook_id,
    url: row.url,
    events: row.events.filter((event): event is string => typeof event === "string"),
    createdAt: nullableText(row.created_at),
    createdBy: nullableText(row.created_by),
  };
}

export function mapWebhookDelivery(value: unknown): WebhookDelivery {
  const row = object(value, "webhook delivery");
  if (typeof row.delivery_id !== "string" || typeof row.event !== "string" || typeof row.ok !== "boolean") {
    throw new ApiError("INVALID_RESPONSE", "The gateway sent an incomplete webhook delivery.");
  }
  return {
    id: row.delivery_id,
    event: row.event,
    at: nullableText(row.at),
    attempts: typeof row.attempts === "number" ? row.attempts : null,
    status: typeof row.status === "number" ? row.status : null,
    ok: row.ok,
    error: nullableText(row.error),
  };
}

export function createDeveloperHttp(call: GatewayCall, kitchen: string): DeveloperHttp {
  return {
    async listWebhooks() {
      const body = object(await call(`${kitchen}/webhooks`), "webhook list");
      if (!Array.isArray(body.webhooks)) {
        throw new ApiError("INVALID_RESPONSE", "The gateway sent webhooks in an unexpected shape.");
      }
      const webhooks = body.webhooks.map(mapWebhook);
      const events = Array.isArray(body.events) ? body.events.filter((event): event is string => typeof event === "string") : [];
      return { webhooks, events };
    },
    async createWebhook(input, actor) {
      const body = (await call(`${kitchen}/webhooks`, {
        method: "POST",
        headers: { "X-User": actor },
        body: JSON.stringify({ url: input.url, events: input.events }),
      })) as Json;
      const hook = mapWebhook(body);
      if (typeof body.secret !== "string" || !body.secret) {
        throw new ApiError("INVALID_RESPONSE", "The gateway did not return the new webhook secret.");
      }
      return { ...hook, secret: body.secret };
    },
    async testWebhook(id, actor) {
      return mapWebhookDelivery(await call(`${kitchen}/webhooks/${encodeURIComponent(id)}/test`, {
        method: "POST",
        headers: { "X-User": actor },
        body: JSON.stringify({}),
      }));
    },
    async getGatewayHealth() {
      const body = object(await call("/health"), "gateway health");
      const mode = body.valio_mode ?? body.valio_api;
      return {
        status: typeof body.status === "string" ? body.status : "unknown",
        valioMode: mode === "live" || mode === "mock" ? mode : "unknown",
      };
    },
  };
}
