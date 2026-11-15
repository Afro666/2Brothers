import { useT } from "@/lib/i18n";

/** Only read-only snapshots: decisions and editable totals never use this cache. */
export function ReadRefresh({ refreshing, outdated, reload }: { refreshing: boolean; outdated?: boolean; reload: () => unknown }) {
  const t = useT();
  if (outdated) return <p role="status" className="text-sm text-muted-foreground">
    {t("Updates are still arriving. These are the last loaded results.")} {" "}
    <button type="button" className="min-h-11 underline" onClick={() => { void reload(); }}>{t("Refresh results")}</button>
  </p>;
  if (!refreshing) return null;
  return <p role="status" className="text-sm text-muted-foreground">{t("Showing previous results while refreshing...")}</p>;
}
