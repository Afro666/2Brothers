import { Navigate } from "@tanstack/react-router";
import { type FormEvent, useMemo, useState } from "react";

import { useApi } from "@/api";
import { MOCK_DEMO_ACCOUNTS, type DemoAccount } from "@/api/mock-auth";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";

function gatewayDemoAccounts(): DemoAccount[] {
  try {
    const value: unknown = JSON.parse(import.meta.env.VITE_DEMO_ACCOUNTS || "null");
    if (
      !Array.isArray(value) ||
      !value.every(
        (account) =>
          account &&
          typeof account.label === "string" &&
          account.label.length > 0 &&
          typeof account.email === "string" &&
          account.email.length > 0 &&
          typeof account.password === "string" &&
          account.password.length > 0,
      )
    ) {
      return [];
    }
    return value as DemoAccount[];
  } catch {
    return [];
  }
}

export function SignInPage() {
  const t = useT();
  const api = useApi();
  const { status, signIn } = useSession();
  const accounts = useMemo(() => (api.live ? gatewayDemoAccounts() : MOCK_DEMO_ACCOUNTS), [api]);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (status === "signed-in") return <Navigate to="/" replace />;

  async function authenticate(loginEmail: string, loginPassword: string) {
    setBusy(true);
    setError(null);
    try {
      await signIn(loginEmail, loginPassword);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setBusy(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void authenticate(email, password);
  }

  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-4">
      <Card className="w-full max-w-md">
        <CardHeader>
          <CardTitle><h1 className="text-xl">{t("Sign in to Kitchen Buyer")}</h1></CardTitle>
          <CardDescription>{t("Use your kitchen account to continue.")}</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {accounts.length > 0 ? (
            <section className="space-y-3" aria-labelledby="demo-accounts-heading">
              <h2 id="demo-accounts-heading" className="text-sm font-medium">
                {t("Demo accounts")}
              </h2>
              <ul className="space-y-2">
                {accounts.map((account) => (
                  <li key={account.email} className="flex items-center justify-between gap-3 rounded-md border p-3">
                    <div className="min-w-0">
                      <div className="text-sm font-medium">{t(account.label)}</div>
                      <div className="truncate text-xs text-muted-foreground">{account.email}</div>
                    </div>
                    <Button
                      type="button"
                      variant="outline"
                      size="sm"
                      disabled={busy}
                      onClick={() => void authenticate(account.email, account.password)}
                    >
                      {t("Sign in as {name}", { name: t(account.label) })}
                    </Button>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}
          <form className="space-y-4" onSubmit={submit}>
            {error ? (
              <Alert variant="destructive">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <div className="space-y-2">
              <Label htmlFor="sign-in-email">{t("Email")}</Label>
              <Input
                id="sign-in-email"
                type="email"
                autoComplete="username"
                required
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                disabled={busy}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="sign-in-password">{t("Password")}</Label>
              <Input
                id="sign-in-password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                disabled={busy}
              />
            </div>
            <Button type="submit" className="w-full" disabled={busy}>
              {busy ? t("Signing in…") : t("Sign in")}
            </Button>
          </form>
        </CardContent>
      </Card>
    </main>
  );
}
