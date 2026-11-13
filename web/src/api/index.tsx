import { createContext, type ReactNode, useContext, useState } from "react";

import { createHttpApi } from "@/api/http";
import { createMockApi } from "@/api/mock";
import type { Api } from "@/api/types";

export { ApiError } from "@/api/types";
export type { Api, AuditActor, ChefProposal, ProductSearchFilters } from "@/api/types";

/** The mock unless `VITE_GATEWAY_URL` is set and `VITE_USE_MOCKS` is "false". */
export function getApi(): Api {
  const gatewayUrl: string | undefined = import.meta.env.VITE_GATEWAY_URL;
  return gatewayUrl && import.meta.env.VITE_USE_MOCKS === "false" ? createHttpApi(gatewayUrl) : createMockApi();
}

const ApiContext = createContext<Api | null>(null);

/** Tests pass their own `api`; the app lets it pick from the environment once. */
export function ApiProvider({ api, children }: { api?: Api; children: ReactNode }) {
  const [fallback] = useState(() => api ?? getApi());
  return <ApiContext.Provider value={api ?? fallback}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  const api = useContext(ApiContext);
  if (!api) throw new Error("useApi must be used within ApiProvider");
  return api;
}
