import { useEffect, useState } from "react";

import { useApi } from "@/api";
import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { auditActorForRole, useRole } from "@/lib/role";
import { cn } from "@/lib/utils";
import { useAsync } from "@/lib/use-async";
import type { DemandClass, KitchenSettings } from "@/types";

const ALLERGENS: Record<string, string> = {
  AM: "Milk",
  AW: "Gluten cereals",
  AE: "Egg",
  AF: "Fish",
  AN: "Tree nuts",
  AP: "Peanuts",
  AS: "Sesame",
  AY: "Soy",
};
const DEMAND_CLASSES: { key: DemandClass; name: string; description: string }[] = [
  { key: "A", name: "A", description: "Menu-critical" },
  { key: "B", name: "B", description: "Regular" },
  { key: "C", name: "C", description: "Nice to have" },
];
const clone = (settings: KitchenSettings): KitchenSettings => structuredClone(settings);

function parseNumber(value: string): number {
  return value === "" ? Number.NaN : Number(value);
}

export function SettingsPage() {
  const api = useApi();
  const { role } = useRole();
  const actor = auditActorForRole(role);
  const state = useAsync(() => api.getKitchenSettings(), [api]);
  const [draft, setDraft] = useState<KitchenSettings | null>(null);
  const [original, setOriginal] = useState<KitchenSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (state.status === "ready") {
      setDraft(clone(state.data));
      setOriginal(clone(state.data));
    }
  }, [state.status, state.status === "ready" ? state.data : null]);

  const changed = draft !== null && original !== null && JSON.stringify(draft) !== JSON.stringify(original);

  function update(updateDraft: (current: KitchenSettings) => KitchenSettings) {
    setDraft((current) => (current ? updateDraft(current) : current));
    setSaveError(null);
    setSaved(false);
  }

  async function saveSettings() {
    if (!draft) return;
    setSaving(true);
    setSaveError(null);
    setSaved(false);
    try {
      const settings = await api.saveKitchenSettings(clone(draft), actor);
      setDraft(clone(settings));
      setOriginal(clone(settings));
      setSaved(true);
    } catch (error) {
      setSaveError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  }

  function resetChanges() {
    if (original) setDraft(clone(original));
    setSaveError(null);
    setSaved(false);
  }

  const allergenCodes = draft ? [...new Set([...Object.keys(ALLERGENS), ...draft.excludedAllergens])].sort() : [];

  return (
    <AppShell activeId="settings">
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">Settings</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            How the Buyer sizes orders for this kitchen. A person still approves every order.
          </p>
        </header>
        {state.status === "loading" ? <LoadingState label="Loading settings" /> : null}
        {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
        {state.status === "ready" && draft === null ? (
          <EmptyState title="Settings are unavailable">The settings service returned no kitchen settings.</EmptyState>
        ) : null}
        {state.status === "ready" && draft ? (
          <form
            className="space-y-5"
            noValidate
            onSubmit={(event) => {
              event.preventDefault();
              void saveSettings();
            }}
          >
            <Card>
              <CardHeader>
                <CardTitle>Service level</CardTitle>
                <CardDescription>Target service level by demand class.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-4">
                {DEMAND_CLASSES.map(({ key, description }) => (
                  <div key={key} className="grid gap-2 sm:grid-cols-[1fr_12rem] sm:items-center">
                    <Label htmlFor={`service-${key}`}>
                      {key} — {description}
                    </Label>
                    <div className="relative">
                      <Input
                        id={`service-${key}`}
                        type="number"
                        min="50"
                        max="99.9"
                        step="0.1"
                        value={Number.isNaN(draft.serviceLevelPercent[key]) ? "" : draft.serviceLevelPercent[key]}
                        onChange={(event) => {
                          const value = parseNumber(event.currentTarget.value);
                          update((current) => ({
                            ...current,
                            serviceLevelPercent: { ...current.serviceLevelPercent, [key]: value },
                          }));
                        }}
                      />
                      <span
                        className={cn(
                          "pointer-events-none absolute inset-y-0 right-3 flex items-center text-sm",
                          "text-muted-foreground",
                        )}
                      >
                        %
                      </span>
                    </div>
                  </div>
                ))}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Days of cover</CardTitle>
                <CardDescription>Maximum days of stock to order for each category.</CardDescription>
              </CardHeader>
              <CardContent className="space-y-3">
                {draft.maxDaysOfCover.map((rule, index) => (
                  <div
                    key={`${index}-${rule.category}`}
                    className="grid gap-2 sm:grid-cols-[1fr_10rem_auto] sm:items-end"
                  >
                    <div className="space-y-1.5">
                      <Label htmlFor={`cover-category-${index}`}>Category</Label>
                      <Input
                        id={`cover-category-${index}`}
                        value={rule.category}
                        onChange={(event) => {
                          const category = event.currentTarget.value;
                          update((current) => ({
                            ...current,
                            maxDaysOfCover: current.maxDaysOfCover.map((item, itemIndex) =>
                              itemIndex === index ? { ...item, category } : item,
                            ),
                          }));
                        }}
                      />
                    </div>
                    <div className="space-y-1.5">
                      <Label htmlFor={`cover-days-${index}`}>Days</Label>
                      <Input
                        id={`cover-days-${index}`}
                        type="number"
                        min="1"
                        step="1"
                        value={Number.isNaN(rule.maxDays) ? "" : rule.maxDays}
                        onChange={(event) => {
                          const maxDays = parseNumber(event.currentTarget.value);
                          update((current) => ({
                            ...current,
                            maxDaysOfCover: current.maxDaysOfCover.map((item, itemIndex) =>
                              itemIndex === index ? { ...item, maxDays } : item,
                            ),
                          }));
                        }}
                      />
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      aria-label={`Remove ${rule.category || "category"}`}
                      onClick={() =>
                        update((current) => ({
                          ...current,
                          maxDaysOfCover: current.maxDaysOfCover.filter((_, itemIndex) => itemIndex !== index),
                        }))
                      }
                    >
                      Remove
                    </Button>
                  </div>
                ))}
                <Button
                  type="button"
                  variant="outline"
                  onClick={() =>
                    update((current) => ({
                      ...current,
                      maxDaysOfCover: [...current.maxDaysOfCover, { category: "", maxDays: 1 }],
                    }))
                  }
                >
                  Add category
                </Button>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Stock-out demand cap</CardTitle>
                <CardDescription>Maximum factor used to scale demand observed during a stock-out.</CardDescription>
              </CardHeader>
              <CardContent className="max-w-xs">
                <Label htmlFor="stock-out-cap">Maximum scaling factor</Label>
                <Input
                  id="stock-out-cap"
                  className="mt-1.5"
                  type="number"
                  min="1"
                  max="3"
                  step="0.1"
                  value={Number.isNaN(draft.stockOutDemandCap) ? "" : draft.stockOutDemandCap}
                  onChange={(event) => {
                    const stockOutDemandCap = parseNumber(event.currentTarget.value);
                    update((current) => ({ ...current, stockOutDemandCap }));
                  }}
                />
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Budget warnings</CardTitle>
                <CardDescription>Leave a value empty to turn that warning off.</CardDescription>
              </CardHeader>
              <CardContent className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="budget-order">Per order (ex VAT, €)</Label>
                  <Input
                    id="budget-order"
                    type="number"
                    min="0"
                    step="0.01"
                    value={draft.budgetWarningPerOrderExVat ?? ""}
                    onChange={(event) => {
                      const value = event.currentTarget.value === "" ? null : Number(event.currentTarget.value);
                      update((current) => ({ ...current, budgetWarningPerOrderExVat: value }));
                    }}
                  />
                  <p className="text-xs text-muted-foreground">Leave empty for no warning.</p>
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="budget-week">Per week (ex VAT, €)</Label>
                  <Input
                    id="budget-week"
                    type="number"
                    min="0"
                    step="0.01"
                    value={draft.budgetWarningPerWeekExVat ?? ""}
                    onChange={(event) => {
                      const value = event.currentTarget.value === "" ? null : Number(event.currentTarget.value);
                      update((current) => ({ ...current, budgetWarningPerWeekExVat: value }));
                    }}
                  />
                  <p className="text-xs text-muted-foreground">Leave empty for no warning.</p>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Allergen rules</CardTitle>
                <CardDescription>
                  Products containing or possibly containing a selected allergen are refused.
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-2">
                {allergenCodes.map((code) => {
                  const id = `allergen-${code}`;
                  return (
                    <div key={code} className="flex items-center gap-2">
                      <Checkbox
                        id={id}
                        checked={draft.excludedAllergens.includes(code)}
                        onCheckedChange={(checked) => {
                          update((current) => ({
                            ...current,
                            excludedAllergens: checked
                              ? [...new Set([...current.excludedAllergens, code])]
                              : current.excludedAllergens.filter((item) => item !== code),
                          }));
                        }}
                      />
                      <Label htmlFor={id}>
                        {code} {ALLERGENS[code] ?? `(GS1 code ${code})`}
                      </Label>
                    </div>
                  );
                })}
              </CardContent>
            </Card>

            {saveError ? (
              <div role="alert" className="rounded-lg border border-destructive/40 p-4 text-sm">
                {saveError}
              </div>
            ) : null}
            {saved ? (
              <p role="status" className="text-sm font-medium text-primary">
                Settings saved
              </p>
            ) : null}
            <div className="flex flex-wrap gap-3">
              <Button type="submit" disabled={!changed || saving}>
                {saving ? "Saving…" : "Save settings"}
              </Button>
              <Button type="button" variant="outline" disabled={!changed || saving} onClick={resetChanges}>
                Reset changes
              </Button>
            </div>
          </form>
        ) : null}
      </div>
    </AppShell>
  );
}
