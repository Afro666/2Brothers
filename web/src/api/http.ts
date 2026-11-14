import type { Api } from "@/api/types";
import { ApiError } from "@/api/types";

/** One JSON call to the gateway. Gateway errors (`{"error": {code, message}}`) become `ApiError`. */
export async function gatewayRequest(baseUrl: string, path: string, init?: RequestInit): Promise<unknown> {
  let response: Response;
  try {
    response = await fetch(`${baseUrl.replace(/\/$/, "")}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError("NETWORK", "Could not reach the gateway.");
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new ApiError("INVALID_RESPONSE", "The gateway did not return JSON.");
  }
  if (!response.ok) {
    const error = (body as { error?: { code?: unknown; message?: unknown } } | null)?.error;
    throw new ApiError(
      typeof error?.code === "string" ? error.code : "GATEWAY_ERROR",
      typeof error?.message === "string" ? error.message : `The gateway answered ${response.status}.`,
    );
  }
  return body;
}

/**
 * The real gateway. docs/contract.md defines only the agent's MCP tools so
 * far; the routes the screens need (approvals, orders, audit by order, chef
 * requests, the product row) are proposed in a contract PR. Until they land,
 * every method says so instead of guessing a shape.
 *
 * Non-method properties stay `undefined`: `live` (the optional set of live
 * methods) so pages fall back to the error state, and `then` so the object
 * is never mistaken for a promise.
 */
const NOT_METHODS = new Set<PropertyKey>(["live", "then"]);

export function createHttpApi(_baseUrl: string): Api {
  return new Proxy({} as Api, {
    get(_target, prop) {
      if (typeof prop === "symbol" || NOT_METHODS.has(prop)) return undefined;
      return async () => {
        throw new ApiError("NOT_SERVED", "The gateway does not serve this yet.");
      };
    },
  });
}
