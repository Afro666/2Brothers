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
 */
export function createHttpApi(_baseUrl: string): Api {
  const notInContract = async (): Promise<never> => {
    throw new ApiError("NOT_IN_CONTRACT", "The gateway contract does not define this route yet.");
  };
  return {
    listApprovals: notInContract,
    getApproval: notInContract,
    approve: notInContract,
    reject: notInContract,
    listOrders: notInContract,
    getOrder: notInContract,
    listAudit: notInContract,
    submitChefRequest: notInContract,
    searchProducts: notInContract,
    getMandate: notInContract,
  };
}
