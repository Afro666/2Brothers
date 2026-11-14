import { type FormEvent, useEffect, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import type { NotificationPreferences } from "@/api/types";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { SampleData } from "@/components/purchasing/sample-data";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { useSession } from "@/lib/session";
import { useAsync } from "@/lib/use-async";
import { useT } from "@/lib/i18n";
import { SettingsSection } from "@/pages/settings/section";

export const EVENTS: { key: keyof NotificationPreferences; title: string; description: string }[] = [
  { key: "approvalWaiting", title: "Approval waiting", description: "A proposal needs a person to approve or reject it." },
  { key: "cutoffTwoHours", title: "Cut-off in 2 hours", description: "An order cut-off is approaching for a needed delivery." },
  { key: "recallAlert", title: "Recall alert", description: "A recall may affect a product used by this kitchen." },
  { key: "orderConfirmed", title: "Order confirmed", description: "The supplier has confirmed a placed order." },
];

export function NotificationsSection() {
  const t = useT();
  const api = useApi();
  const { session } = useSession();
  const state = useAsync(() => api.getNotificationPreferences(), [api]);
  const [draft, setDraft] = useState<NotificationPreferences | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const canApprove = session?.canApprove === true;
  const canSave = !api.live || api.live.has("saveNotificationPreferences");
  const canEdit = canApprove && canSave;

  useEffect(() => {
    if (state.status === "ready") setDraft({ ...state.data });
  }, [state.status, state.status === "ready" ? state.data : null]);

  async function save(event: FormEvent) {
    event.preventDefault();
    if (!draft) return;
    setSaving(true);
    setError(null);
    try {
      const saved = await api.saveNotificationPreferences(draft, "human");
      setDraft({ ...saved });
      toast.success(t("Notification preferences saved"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSaving(false);
    }
  }

  return (
    <SettingsSection title="Notifications" description="Choose which events appear in the app. E-mail delivery will be added later.">
      <SampleData of="getNotificationPreferences" />
      {state.status === "loading" ? <LoadingState label={t("Loading notification preferences")} /> : null}
      {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
      {state.status === "ready" && draft ? (
        <Card className="max-w-2xl">
          <CardHeader>
            <CardTitle>{t("In-app alerts")}</CardTitle>
            <CardDescription>{t("Recall alerts are strongly recommended for every kitchen.")}</CardDescription>
          </CardHeader>
          <CardContent>
            <form className="space-y-5" onSubmit={(event) => void save(event)}>
              {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
              {!canEdit ? <p className="text-sm text-muted-foreground">{canApprove ? t("Saving notification preferences is not available on this server yet; the choices below are sample data.") : t("Only an approver can change notification preferences.")}</p> : null}
              {EVENTS.map(({ key, title, description }) => (
                <div key={key} className="flex items-start gap-3">
                  <Checkbox
                    id={`notification-${key}`}
                    className="mt-0.5"
                    checked={draft[key]}
                    disabled={!canEdit || saving}
                    onCheckedChange={(checked) => {
                      setDraft((current) => current ? { ...current, [key]: checked === true } : current);
                      setError(null);
                    }}
                  />
                  <div className="space-y-1">
                    <Label htmlFor={`notification-${key}`}>{t(title)}</Label>
                    <p className="text-sm text-muted-foreground">{t(description)}</p>
                  </div>
                </div>
              ))}
              {canEdit ? <Button type="submit" disabled={saving}>{saving ? t("Saving…") : t("Save notifications")}</Button> : null}
            </form>
          </CardContent>
        </Card>
      ) : null}
    </SettingsSection>
  );
}
