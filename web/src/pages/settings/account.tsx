import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SettingsSection } from "@/pages/settings/section";

export function AccountSection() {
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
      setError("Passwords do not match.");
      return;
    }
    if (next.length < 10) {
      setError("New password must be at least 10 characters.");
      return;
    }
    setBusy(true);
    try {
      await api.changePassword(current, next);
      setCurrent("");
      setNext("");
      setRepeat("");
      toast.success("Password changed");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  return (
    <SettingsSection title="Account" description="Manage the password for your kitchen account.">
      <Card className="max-w-lg">
        <CardHeader>
          <CardTitle>Change password</CardTitle>
        </CardHeader>
        <CardContent>
          <form className="space-y-4" onSubmit={(event) => void submit(event)}>
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <div className="space-y-2">
              <Label htmlFor="current-password">Current password</Label>
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
              <Label htmlFor="new-password">New password</Label>
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
                Use at least 10 characters.
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="repeat-password">Repeat new password</Label>
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
              {busy ? "Changing password…" : "Change password"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </SettingsSection>
  );
}
