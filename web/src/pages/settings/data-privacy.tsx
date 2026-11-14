import { type FormEvent, useEffect, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { SampleData } from "@/components/purchasing/sample-data";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { downloadKitchenExport } from "@/lib/kitchen-export";
import { useSession } from "@/lib/session";
import { useAsync } from "@/lib/use-async";
import { useT } from "@/lib/i18n";
import { SettingsSection } from "@/pages/settings/section";
import type { SharingConsent } from "@/types";

export function DataPrivacySection() {
  const t = useT();
  const api = useApi();
  const { session } = useSession();
  const canEdit = session?.canApprove === true;
  const canRequestDeletion = canEdit && (!api.live || api.live.has("requestKitchenDeletion"));
  const state = useAsync(async () => {
    const [sharing, suppliers] = await Promise.all([api.getSharing(), api.listSuppliers()]);
    return { sharing, suppliers };
  }, [api]);
  const [sharing, setSharing] = useState<SharingConsent[]>([]);
  const [sharingError, setSharingError] = useState<string | null>(null);
  const [busySupplier, setBusySupplier] = useState<string | null>(null);
  const [exporting, setExporting] = useState<"json" | "csv" | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [confirmation, setConfirmation] = useState("");
  const [deleteError, setDeleteError] = useState<string | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [requestId, setRequestId] = useState<string | null>(null);

  useEffect(() => {
    if (state.status === "ready") setSharing(structuredClone(state.data.sharing));
  }, [state.status, state.status === "ready" ? state.data : null]);

  async function changeSharing(supplierId: string, shared: boolean) {
    const name = state.status === "ready" ? state.data.suppliers.find((row) => row.id === supplierId)?.name : null;
    setBusySupplier(supplierId);
    setSharingError(null);
    try {
      const next = await api.setSharing(supplierId, shared, "human");
      setSharing(structuredClone(next));
      toast.success(
        shared
          ? t("Forecast sharing turned on for {supplier}", { supplier: name ?? t("unknown supplier") })
          : t("Forecast sharing turned off for {supplier}", { supplier: name ?? t("unknown supplier") }),
      );
    } catch (error) {
      setSharingError(error instanceof Error ? error.message : String(error));
    } finally {
      setBusySupplier(null);
    }
  }

  async function exportData(format: "json" | "csv") {
    setExporting(format);
    setExportError(null);
    try {
      const [orders, proposals, audit] = await Promise.all([api.listOrders(), api.listApprovals(), api.listAudit()]);
      downloadKitchenExport(format, { orders, proposals, audit });
      toast.success(t("{format} export downloaded", { format: format.toUpperCase() }));
    } catch (error) {
      setExportError(error instanceof Error ? error.message : String(error));
    } finally {
      setExporting(null);
    }
  }

  function openDeleteDialog(open: boolean) {
    setDeleteOpen(open);
    setConfirmation("");
    setDeleteError(null);
  }

  async function requestDeletion(event: FormEvent) {
    event.preventDefault();
    if (confirmation !== "DELETE") {
      setDeleteError(t("Type DELETE to confirm the request."));
      return;
    }
    setRequesting(true);
    setDeleteError(null);
    try {
      const request = await api.requestKitchenDeletion(confirmation, "human");
      setRequestId(request.id);
      setDeleteOpen(false);
      setConfirmation("");
      toast.success(t("Kitchen deletion request recorded"));
    } catch (error) {
      setDeleteError(error instanceof Error ? error.message : String(error));
    } finally {
      setRequesting(false);
    }
  }

  return (
    <SettingsSection title="Data & privacy" description="Download kitchen records, control forecast sharing and request deletion without deleting anything silently.">
      <div className="grid items-start gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>{t("Export kitchen data")}</CardTitle>
            <CardDescription>{t("Download current orders, proposals and audit events as JSON or a quoted, spreadsheet-safe CSV file.")}</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {exportError ? <p role="alert" className="text-sm text-destructive">{exportError}</p> : null}
            <div className="flex flex-wrap gap-2">
              <Button type="button" variant="outline" disabled={exporting !== null} onClick={() => void exportData("json")}>{exporting === "json" ? t("Preparing…") : t("Download JSON")}</Button>
              <Button type="button" variant="outline" disabled={exporting !== null} onClick={() => void exportData("csv")}>{exporting === "csv" ? t("Preparing…") : t("Download CSV")}</Button>
            </div>
            <p className="text-sm text-muted-foreground">{t("CSV cells are quoted. Cells beginning with =, +, - or @ are prefixed with an apostrophe to prevent spreadsheet formulas.")}</p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{t("Data retention")}</CardTitle>
            <CardDescription>{t("Retention period: unknown. Your gateway administrator controls storage and retention.")}</CardDescription>
          </CardHeader>
          <CardContent><p className="text-sm text-muted-foreground">{t("Exporting data or requesting deletion does not change stored records. Audit entries remain part of the kitchen's tamper-evident history.")}</p></CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>{t("Forecast sharing")}</CardTitle>
          <CardDescription>{t("Each supplier sees this kitchen's name and expected product needs, never menus, recipes, prices from other suppliers or stock counts. Every change writes an audit entry.")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          {sharingError ? <p role="alert" className="text-sm text-destructive">{sharingError}</p> : null}
          {!canEdit ? <p className="text-sm text-muted-foreground">{t("Only an approver can change forecast sharing.")}</p> : null}
          {state.status === "loading" ? <LoadingState label={t("Loading forecast sharing")} /> : null}
          {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
          {state.status === "ready" && sharing.length === 0 ? <EmptyState title={t("No supplier sharing records")}>{t("No forecast consent records were returned.")}</EmptyState> : null}
          {state.status === "ready" && sharing.length > 0 ? (
            <ul className="divide-y" aria-label={t("Supplier forecast sharing")}>
              {sharing.map((consent) => {
                const name = state.data.suppliers.find((row) => row.id === consent.supplierId)?.name ?? t("unknown supplier");
                return <li key={consent.supplierId} className="flex items-start gap-3 py-4 first:pt-0 last:pb-0">
                  <Checkbox id={`sharing-${consent.supplierId}`} className="mt-0.5" checked={consent.shared} disabled={!canEdit || busySupplier !== null} onCheckedChange={(checked) => void changeSharing(consent.supplierId, checked === true)} />
                  <div><Label htmlFor={`sharing-${consent.supplierId}`}>{t("Share forecast with {supplier}", { supplier: name })}</Label><p className="mt-1 text-sm text-muted-foreground">{consent.shared ? t("Sharing is on.") : t("Sharing is off.")} {t("Supplier ID:")} <span className="font-mono">{consent.supplierId}</span></p></div>
                </li>;
              })}
            </ul>
          ) : null}
        </CardContent>
      </Card>

      <Card className="border-destructive/40">
        <CardHeader>
          <div className="flex flex-wrap items-center gap-2"><CardTitle>{t("Request kitchen deletion")}</CardTitle><SampleData of="requestKitchenDeletion" /></div>
          <CardDescription>{t("This records a deletion request for an administrator. It never deletes the kitchen or its data.")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          {requestId ? <p className="text-sm">{t("Request")} <span className="font-mono">{requestId}</span> {t("was recorded. No data was deleted.")}</p> : null}
          {api.live && !api.live.has("requestKitchenDeletion") ? <p className="text-sm text-muted-foreground">{t("The gateway has no deletion-request route, so this sample request form is unavailable.")}</p> : null}
          {canRequestDeletion ? <Button type="button" variant="destructive" onClick={() => openDeleteDialog(true)}>{t("Request deletion")}</Button> : !canEdit ? <p className="text-sm text-muted-foreground">{t("Only an approver can request kitchen deletion.")}</p> : null}
        </CardContent>
      </Card>

      <Dialog open={deleteOpen} onOpenChange={openDeleteDialog}>
        <DialogContent className="max-w-lg">
          <DialogHeader><DialogTitle>{t("Request kitchen deletion?")}</DialogTitle><DialogDescription>{t("This only records a request. It does not delete the kitchen, orders, proposals or audit history.")}</DialogDescription></DialogHeader>
          <form className="space-y-4" onSubmit={(event) => void requestDeletion(event)} noValidate>
            {deleteError ? <p role="alert" className="text-sm text-destructive">{deleteError}</p> : null}
            <div className="space-y-2"><Label htmlFor="delete-confirmation">{t("Type DELETE to confirm")}</Label><Input id="delete-confirmation" value={confirmation} autoComplete="off" disabled={requesting} onChange={(event) => { setConfirmation(event.target.value); setDeleteError(null); }} /></div>
            <DialogFooter><Button type="button" variant="outline" disabled={requesting} onClick={() => openDeleteDialog(false)}>{t("Cancel")}</Button><Button type="submit" variant="destructive" disabled={requesting}>{requesting ? t("Recording…") : t("Record deletion request")}</Button></DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}
