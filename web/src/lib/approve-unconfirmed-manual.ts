import { useApi } from "@/api";
import { useAsync } from "@/lib/use-async";

/**
 * The kitchen's approve_unconfirmed_manual setting as a plain boolean.
 * Unknown means off: false while loading or when the request fails.
 */
export function useApproveUnconfirmedManual(): boolean {
  const api = useApi();
  const setting = useAsync(
    () => api.getKitchenSettings().then((settings) => settings.approveUnconfirmedManual).catch(() => false),
    [api],
  );
  return setting.status === "ready" && setting.data;
}
