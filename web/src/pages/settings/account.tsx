import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useT } from "@/lib/i18n";
import { SettingsSection } from "@/pages/settings/section";

export function AccountSection() {
  const t = useT();
  const api = useApi();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent) {
    event.preventDefault();
    setError(null);
    if (next !== repeat) {
      setError(t("Passwords do not match."));
      return;
    }
    if (next.length < 10) {
      setError(t("New password must be at least 10 characters."));
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setRepeat("");
      toast.success(t("Password changed"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsSection title={t("Account")} description={t("Manage the password for your kitchen account.")}>
      <Card className="max-w-lg">
        <CardHeader>
          <CardTitle>{t("Change password")}</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={(event) => void submit(event)}>
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <div className="space-y-2">
              <Label htmlFor="current-password">{t("Current password")}</Label>
              <Input
                id="current-password"
                type="password"
                autoComplete="current-password"
                required
                value={current}
                onChange={(event) => setCurrent(event.target.value)}
                disabled={busy}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="new-password">{t("New password")}</Label>
              <Input
                id="new-password"
                type="password"
                autoComplete="new-password"
                aria-describedby="new-password-hint"
                required
                value={next}
                onChange={(event) => setNext(event.target.value)}
                disabled={busy}
              />
              <p id="new-password-hint" className="text-xs text-muted-foreground">
                {t("Use at least 10 characters.")}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="repeat-password">{t("Repeat new password")}</Label>
              <Input
                id="repeat-password"
                type="password"
                autoComplete="new-password"
                required
                value={repeat}
                onChange={(event) => setRepeat(event.target.value)}
                disabled={busy}
              />
            </div>
            <Button type="submit" disabled={busy}>
              {busy ? t("Changing password…") : t("Change password")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </SettingsSection>
  );
}
