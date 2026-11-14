import { useEffect, useId, useMemo, useRef, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import type { Draft } from "@/api/types";
import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardAction, CardContent, CardFooter, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Dialog,
  DialogBody,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatEur, formatNumber } from "@/lib/format";
import { auditActorForRole, useRole } from "@/lib/role";
import { TONE_CLASSES } from "@/lib/tone";
import { useAsync } from "@/lib/use-async";
import { useT } from "@/lib/i18n";
import type { SharingConsent, Supplier, SupplierAdapter } from "@/types";

export const ADAPTER_LABEL: Record<SupplierAdapter, string> = {
  valio_api: "Live API",
  manual: "Manual entry",
  csv: "CSV price list",
};

const ADAPTERS: SupplierAdapter[] = ["valio_api", "manual", "csv"];

export const DAY_LABEL: Record<number, string> = {
  1: "Mon",
  2: "Tue",
  3: "Wed",
  4: "Thu",
  5: "Fri",
  6: "Sat",
  7: "Sun",
};

const DAYS = [1, 2, 3, 4, 5, 6, 7];

type Parsed<T> = { value: T | null; error: string | null };

/** "HH:MM" typed by a person, or null when empty. */
function parseTime(value: string): Parsed<string> {
  if (!value.trim()) return { value: null, error: null };
  const match = /^(\d{1,2}):(\d{2})$/.exec(value.trim());
  if (!match) return { value: null, error: "Enter a time in HH:MM format." };
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return { value: null, error: "Enter a valid time." };
  return { value: `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`, error: null };
}

function parseDecimal(value: string): Parsed<number> {
  const trimmed = value.trim().replace(",", ".");
  if (!trimmed) return { value: null, error: null };
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) return { value: null, error: "Enter a valid amount." };
  if (parsed < 0) return { value: null, error: "Value cannot be negative." };
  return { value: parsed, error: null };
}

function parseCount(value: string): Parsed<number> {
  const trimmed = value.trim();
  if (!trimmed) return { value: null, error: null };
  const parsed = Number(trimmed);
  if (!Number.isInteger(parsed)) return { value: null, error: "Enter a whole number." };
  if (parsed < 0) return { value: null, error: "Value cannot be negative." };
  return { value: parsed, error: null };
}

type SharingState =
  { status: "loading" } | { status: "error"; message: string } | { status: "ready"; data: SharingConsent[] };

interface FormState {
  name: string;
  adapter: SupplierAdapter;
  freeDelivery: string;
  deliveryFee: string;
  orderDays: number[];
  cutoff: string;
  leadTime: string;
}

function formFromSupplier(supplier: Supplier | null): FormState {
  return {
    name: supplier?.name ?? "",
    adapter: supplier?.adapter ?? "manual",
    freeDelivery: supplier?.freeDeliveryThresholdEur == null ? "" : String(supplier.freeDeliveryThresholdEur),
    deliveryFee: supplier?.deliveryFeeEur == null ? "" : String(supplier.deliveryFeeEur),
    orderDays: supplier?.orderDays ? [...supplier.orderDays] : [],
    cutoff: supplier?.cutoffTime ?? "",
    leadTime: supplier?.leadTimeDays == null ? "" : String(supplier.leadTimeDays),
  };
}

function draftFromForm(
  form: FormState,
  supplier: Supplier | null,
  parsed: {
    freeDelivery: Parsed<number>;
    deliveryFee: Parsed<number>;
    cutoff: Parsed<string>;
    leadTime: Parsed<number>;
  },
): Draft<Supplier> {
  return {
    ...(supplier ? { id: supplier.id } : {}),
    name: form.name,
    adapter: form.adapter,
    freeDeliveryThresholdEur: parsed.freeDelivery.value,
    deliveryFeeEur: parsed.deliveryFee.value,
    orderDays: form.orderDays.length > 0 ? [...form.orderDays].sort((a, b) => a - b) : null,
    cutoffTime: parsed.cutoff.value,
    leadTimeDays: parsed.leadTime.value,
  };
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

function NotSet() {
  const t = useT();
  return <span className="text-muted-foreground">{t("not set")}</span>;
}

function eur(value: number | null) {
  return value == null ? <NotSet /> : <span className="tabular-nums">{formatEur(value)}</span>;
}

function Terms({ supplier }: { supplier: Supplier }) {
  const t = useT();
  const days = supplier.orderDays;
  return (
    <dl className="grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
      <div>
        <dt className="text-xs text-muted-foreground">{t("Free delivery from")}</dt>
        <dd>{eur(supplier.freeDeliveryThresholdEur)}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">{t("Delivery fee")}</dt>
        <dd>{eur(supplier.deliveryFeeEur)}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">{t("Order days")}</dt>
        <dd>{days && days.length > 0 ? days.map((day) => t(DAY_LABEL[day] ?? String(day))).join(", ") : <NotSet />}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">{t("Order cut-off")}</dt>
        <dd>{supplier.cutoffTime ?? <NotSet />}</dd>
      </div>
      <div>
        <dt className="text-xs text-muted-foreground">{t("Lead time")}</dt>
        <dd>
          {supplier.leadTimeDays == null ? (
            <NotSet />
          ) : (
            supplier.leadTimeDays === 1
              ? t("{count} day", { count: formatNumber(supplier.leadTimeDays) })
              : t("{count} days", { count: formatNumber(supplier.leadTimeDays) })
          )}
        </dd>
      </div>
    </dl>
  );
}

function SupplierForm({
  supplier,
  onClose,
  onSaved,
}: {
  supplier: Supplier | null;
  onClose: () => void;
  onSaved: () => void;
}) {
  const t = useT();
  const api = useApi();
  const [form, setForm] = useState<FormState>(() => formFromSupplier(supplier));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const parsed = {
    freeDelivery: parseDecimal(form.freeDelivery),
    deliveryFee: parseDecimal(form.deliveryFee),
    cutoff: parseTime(form.cutoff),
    leadTime: parseCount(form.leadTime),
  };
  const idPrefix = useId();
  const fieldId = (name: string) => `${idPrefix}-${name}`;

  function toggleDay(day: number, checked: boolean) {
    setForm((current) => ({
      ...current,
      orderDays: checked ? [...current.orderDays, day] : current.orderDays.filter((value) => value !== day),
    }));
  }

  async function save() {
    if (Object.values(parsed).some((field) => field.error)) return;
    setBusy(true);
    setError(null);
    try {
      await api.saveSupplier(draftFromForm(form, supplier, parsed));
      toast.success(t("Supplier saved"));
      onSaved();
      onClose();
    } catch (e) {
      setError(messageOf(e));
      setBusy(false);
    }
  }

  return (
    <>
      {error ? (
        <p role="alert" className={`rounded-md border px-3 py-2 text-sm ${TONE_CLASSES.danger}`}>
          {error}
        </p>
      ) : null}
      <DialogBody className="space-y-4">
        <div className="grid gap-2">
          <Label htmlFor={fieldId("name")}>{t("Name")}</Label>
          <Input
            id={fieldId("name")}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            autoFocus
          />
        </div>
        <div className="grid gap-2">
          <Label htmlFor={fieldId("adapter")}>{t("How orders reach them")}</Label>
          <Select
            value={form.adapter}
            onValueChange={(value) => setForm({ ...form, adapter: value as SupplierAdapter })}
          >
            <SelectTrigger id={fieldId("adapter")} className="w-full">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {ADAPTERS.map((adapter) => (
                <SelectItem key={adapter} value={adapter}>
                  {t(ADAPTER_LABEL[adapter])}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-2">
            <Label htmlFor={fieldId("free-delivery")}>{t("Free delivery from (EUR)")}</Label>
            <Input
              id={fieldId("free-delivery")}
              type="text"
              inputMode="decimal"
              min="0"
              step="0.01"
              placeholder={t("Not set")}
              value={form.freeDelivery}
              onChange={(e) => setForm({ ...form, freeDelivery: e.target.value })}
            />
            {parsed.freeDelivery.error ? (
              <p role="alert" className="text-sm text-destructive">
                {t(parsed.freeDelivery.error)}
              </p>
            ) : null}
          </div>
          <div className="grid gap-2">
            <Label htmlFor={fieldId("delivery-fee")}>{t("Delivery fee (EUR)")}</Label>
            <Input
              id={fieldId("delivery-fee")}
              type="text"
              inputMode="decimal"
              min="0"
              step="0.01"
              placeholder={t("Not set")}
              value={form.deliveryFee}
              onChange={(e) => setForm({ ...form, deliveryFee: e.target.value })}
            />
            {parsed.deliveryFee.error ? (
              <p role="alert" className="text-sm text-destructive">
                {t(parsed.deliveryFee.error)}
              </p>
            ) : null}
          </div>
          <div className="grid gap-2">
            <Label htmlFor={fieldId("cutoff")}>{t("Order cut-off")}</Label>
            <Input
              id={fieldId("cutoff")}
              type="text"
              placeholder="HH:MM"
              value={form.cutoff}
              onChange={(e) => setForm({ ...form, cutoff: e.target.value })}
            />
            {parsed.cutoff.error ? (
              <p role="alert" className="text-sm text-destructive">
                {t(parsed.cutoff.error)}
              </p>
            ) : null}
          </div>
          <div className="grid gap-2">
            <Label htmlFor={fieldId("lead-time")}>{t("Lead time (days)")}</Label>
            <Input
              id={fieldId("lead-time")}
              type="text"
              inputMode="numeric"
              min="0"
              step="1"
              placeholder={t("Not set")}
              value={form.leadTime}
              onChange={(e) => setForm({ ...form, leadTime: e.target.value })}
            />
            {parsed.leadTime.error ? (
              <p role="alert" className="text-sm text-destructive">
                {t(parsed.leadTime.error)}
              </p>
            ) : null}
          </div>
        </div>
        <fieldset className="grid gap-2">
          <legend className="mb-2 text-sm font-medium">{t("Order days")}</legend>
          <div className="flex flex-wrap gap-3">
            {DAYS.map((day) => {
              const id = fieldId(`day-${day}`);
              return (
                <div key={day} className="flex items-center gap-2">
                  <Checkbox
                    id={id}
                    checked={form.orderDays.includes(day)}
                    onCheckedChange={(checked) => toggleDay(day, checked === true)}
                  />
                  <Label htmlFor={id}>{t(DAY_LABEL[day])}</Label>
                </div>
              );
            })}
          </div>
          {form.orderDays.length === 0 ? (
            <p className="text-xs text-muted-foreground">{t("No days ticked: order days are not set.")}</p>
          ) : null}
        </fieldset>
      </DialogBody>
      <DialogFooter>
        <Button disabled={busy} onClick={() => void save()}>
          {t("Save supplier")}
        </Button>
        <DialogClose asChild>
          <Button variant="outline" disabled={busy}>
            {t("Cancel")}
          </Button>
        </DialogClose>
      </DialogFooter>
    </>
  );
}

function SupplierCard({
  supplier,
  shared,
  sharingPending,
  onEdit,
  onDelete,
  onShare,
}: {
  supplier: Supplier;
  shared: boolean | null;
  sharingPending: boolean;
  onEdit: () => void;
  onDelete: () => void;
  onShare: (shared: boolean) => Promise<void>;
}) {
  const t = useT();
  const shareId = useId();
  const [shareBusy, setShareBusy] = useState(false);
  const [shareError, setShareError] = useState<string | null>(null);

  async function changeShared(next: boolean) {
    setShareBusy(true);
    setShareError(null);
    try {
      await onShare(next);
    } catch (e) {
      setShareError(messageOf(e));
    } finally {
      setShareBusy(false);
    }
  }

  return (
    <Card className="gap-4 tabular-nums">
      <CardHeader>
        <CardTitle className="leading-snug">
          <h3 className="text-base font-semibold">{supplier.name}</h3>
        </CardTitle>
        <CardAction>
          <Badge variant="secondary">{t(ADAPTER_LABEL[supplier.adapter])}</Badge>
        </CardAction>
      </CardHeader>
      <CardContent className="space-y-4">
        <Terms supplier={supplier} />
        <div className="space-y-1 border-t pt-4">
          <div className="flex items-start gap-2">
            <Checkbox
              id={shareId}
              checked={shared === true}
              disabled={shared === null || shareBusy || sharingPending}
              onCheckedChange={(checked) => void changeShared(checked === true)}
            />
            <div className="grid gap-1">
              <Label htmlFor={shareId} className="leading-snug">
                {t("Share our forecast with {supplier}", { supplier: supplier.name })}
              </Label>
              <p className="text-xs text-muted-foreground">
                {t("They see our kitchen's name and what we expect to need, never our menus or prices. Every change is in the audit log.")}
              </p>
            </div>
          </div>
          {shareError ? (
            <p role="alert" className={`rounded-md border px-3 py-2 text-sm ${TONE_CLASSES.danger}`}>
              {shareError}
            </p>
          ) : null}
        </div>
      </CardContent>
      <CardFooter className="gap-2 border-t">
        <Button variant="outline" size="sm" onClick={onEdit}>
          {t("Edit")}
        </Button>
        <Button variant="ghost" size="sm" className="text-danger hover:text-danger" onClick={onDelete}>
          {t("Delete")}
        </Button>
      </CardFooter>
    </Card>
  );
}

export function SuppliersPage() {
  const t = useT();
  const api = useApi();
  const { role } = useRole();
  const actor = auditActorForRole(role);
  const suppliersState = useAsync(() => api.listSuppliers(), [api]);
  // Diff by id: React keeps a card when the same supplier comes back, so per-card errors survive a reload.
  // Derived during render, so a ready state never shows zero rows for one frame.
  const previousRows = useRef<Supplier[]>([]);
  const readyData = suppliersState.status === "ready" ? suppliersState.data : null;
  const rows = useMemo(() => {
    if (!readyData) return previousRows.current;
    return readyData.map((supplier) => {
      const previous = previousRows.current.find((row) => row.id === supplier.id);
      return previous && JSON.stringify(previous) === JSON.stringify(supplier) ? previous : supplier;
    });
  }, [readyData]);
  useEffect(() => {
    previousRows.current = rows;
  }, [rows]);
  const suppliers = { ...suppliersState, data: rows };
  const [sharing, setSharing] = useState<SharingState>({ status: "loading" });
  const [sharingVersion, setSharingVersion] = useState(0);
  const [formDialog, setFormDialog] = useState<{ mode: "add" } | { mode: "edit"; supplier: Supplier } | null>(null);
  const [sharingPending, setSharingPending] = useState(false);
  const [deleting, setDeleting] = useState<Supplier | null>(null);
  const [deleteError, setDeleteError] = useState<{ id: string; message: string } | null>(null);
  const [deleteBusy, setDeleteBusy] = useState(false);
  const titleId = useId();

  useEffect(() => {
    let active = true;
    api.getSharing().then(
      (data) => active && setSharing({ status: "ready", data }),
      (error: unknown) => active && setSharing({ status: "error", message: messageOf(error) }),
    );
    return () => {
      active = false;
    };
  }, [api, sharingVersion]);

  // A supplier without a consent row is simply not shared.
  const sharingById = new Map(
    sharing.status === "ready" ? sharing.data.map((consent) => [consent.supplierId, consent.shared] as const) : [],
  );
  function sharedFor(supplierId: string): boolean | null {
    return sharing.status === "ready" ? (sharingById.get(supplierId) ?? false) : null;
  }

  async function setSupplierSharing(supplierId: string, shared: boolean): Promise<void> {
    setSharingPending(true);
    try {
      const data = await api.setSharing(supplierId, shared, actor);
      setSharing({ status: "ready", data });
      const supplier = suppliers.data.find((item) => item.id === supplierId);
      toast.success(
        supplier
          ? shared
            ? t("Forecast sharing turned on for {supplier}", { supplier: supplier.name })
            : t("Forecast sharing turned off for {supplier}", { supplier: supplier.name })
          : shared
            ? t("Forecast sharing turned on")
            : t("Forecast sharing turned off"),
      );
    } finally {
      setSharingPending(false);
    }
  }

  function openAdd() {
    setFormDialog({ mode: "add" });
  }

  // A fresh form each time, so an earlier failed save does not prefill the next dialog.
  function openEdit(supplier: Supplier) {
    setFormDialog({ mode: "edit", supplier });
  }

  async function confirmDelete() {
    if (!deleting) return;
    setDeleteBusy(true);
    setDeleteError(null);
    try {
      await api.deleteSupplier(deleting.id);
      toast.success(t("Supplier deleted"));
      setDeleting(null);
      suppliers.reload();
    } catch (e) {
      setDeleteError({ id: deleting.id, message: messageOf(e) });
      setDeleting(null);
    } finally {
      setDeleteBusy(false);
    }
  }

  return (
    <AppShell activeId="suppliers">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("Suppliers")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("Who you buy from, and each supplier's terms. Terms are yours to set; nothing is assumed.")}
          </p>
        </header>
        {suppliers.status === "loading" ? <LoadingState label={t("Loading suppliers")} /> : null}
        {suppliers.status === "error" ? (
          <ErrorState message={suppliers.error.message} onRetry={suppliers.reload} />
        ) : null}
        {suppliers.status === "ready" ? (
          <div className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm tabular-nums text-muted-foreground" aria-live="polite">
                {suppliers.data.length === 1 ? t("{count} supplier", { count: suppliers.data.length }) : t("{count} suppliers", { count: suppliers.data.length })}
              </p>
              <Button onClick={openAdd}>{t("Add supplier")}</Button>
            </div>
            {sharing.status === "error" ? (
              <ErrorState message={sharing.message} onRetry={() => setSharingVersion((version) => version + 1)} />
            ) : null}
            {suppliers.data.length === 0 ? (
              <EmptyState title={t("No suppliers yet")}>
                <Button className="mt-3" onClick={openAdd}>
                  {t("Add supplier")}
                </Button>
              </EmptyState>
            ) : (
              <div className="grid gap-4 md:grid-cols-2">
                {suppliers.data.map((supplier) => (
                  <div key={supplier.id} className="space-y-2">
                    <SupplierCard
                      supplier={supplier}
                      shared={sharedFor(supplier.id)}
                      sharingPending={sharingPending}
                      onEdit={() => openEdit(supplier)}
                      onDelete={() => {
                        setDeleteError(null);
                        setDeleting(supplier);
                      }}
                      onShare={(shared) => setSupplierSharing(supplier.id, shared)}
                    />
                    {deleteError?.id === supplier.id ? (
                      <p role="alert" className={`rounded-md border px-3 py-2 text-sm ${TONE_CLASSES.danger}`}>
                        {deleteError.message}
                      </p>
                    ) : null}
                  </div>
                ))}
              </div>
            )}
          </div>
        ) : null}
        <Dialog
          open={formDialog !== null}
          onOpenChange={(open) => {
            if (!open) setFormDialog(null);
          }}
        >
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>
                {formDialog?.mode === "edit" ? t("Edit {name}", { name: formDialog.supplier.name }) : t("Add supplier")}
              </DialogTitle>
              <DialogDescription>
                {t("Leave a field empty when the term is not known. Empty terms show as not set, never as zero.")}
              </DialogDescription>
            </DialogHeader>
            <SupplierForm
              key={formDialog?.mode === "edit" ? `edit-${formDialog.supplier.id}` : "add"}
              supplier={formDialog?.mode === "edit" ? formDialog.supplier : null}
              onClose={() => setFormDialog(null)}
              onSaved={() => {
                suppliers.reload();
                setSharingVersion((version) => version + 1);
              }}
            />
          </DialogContent>
        </Dialog>
        <Dialog open={deleting !== null} onOpenChange={(open) => (open ? undefined : setDeleting(null))}>
          <DialogContent className="max-w-md" aria-labelledby={titleId}>
            <DialogHeader>
              <DialogTitle id={titleId}>{t("Delete {name}?", { name: deleting?.name ?? "" })}</DialogTitle>
              <DialogDescription>
                {t("The supplier is removed from this list. A supplier that still supplies your products cannot be deleted.")}
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <Button variant="destructive" disabled={deleteBusy} onClick={() => void confirmDelete()}>
                {t("Delete supplier")}
              </Button>
              <DialogClose asChild>
                <Button variant="outline" disabled={deleteBusy}>
                  {t("Cancel")}
                </Button>
              </DialogClose>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </AppShell>
  );
}
