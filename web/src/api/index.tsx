import { createContext, type ReactNode, useContext } from "react";

import { createHttpApi } from "@/api/http";
import { createMockApi } from "@/api/mock";
import type { Api } from "@/api/types";

export { ApiError } from "@/api/types";
export type { Api, AuditActor, ChefProposal, LiveEvent, ProductSearchFilters, Session } from "@/api/types";

/** The mock unless `VITE_GATEWAY_URL` is set and `VITE_USE_MOCKS` is "false". */
export function getApi(): Api {
  const gatewayUrl: string | undefined = import.meta.env.VITE_GATEWAY_URL;
  return gatewayUrl && import.meta.env.VITE_USE_MOCKS === "false" ? createHttpApi(gatewayUrl) : createMockApi();
}

const ApiContext = createContext<Api | null>(null);

let defaultApi: Api | null = null;

/** One Api per page, so a remount (e.g. the language switch) keeps the mock's data. */
function getDefaultApi(): Api {
  defaultApi ??= getApi();
  return defaultApi;
}

/** Tests pass their own `api`; the app picks one from the environment once per page. */
export function ApiProvider({ api, children }: { api?: Api; children: ReactNode }) {
  return <ApiContext.Provider value={api ?? getDefaultApi()}>{children}</ApiContext.Provider>;
}

export function useApi(): Api {
  const api = useContext(ApiContext);
  if (!api) throw new Error("useApi must be used within ApiProvider");
  return api;
}
