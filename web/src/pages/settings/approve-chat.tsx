import { Link } from "@tanstack/react-router";
import { type FormEvent, useRef, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import { ApiError, type ApprovalToken, type CreatedApprovalToken } from "@/api/types";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDateTime } from "@/lib/format";
import { useT } from "@/lib/i18n";
import { useSession } from "@/lib/session";
import { useAsync } from "@/lib/use-async";
import { SettingsSection } from "@/pages/settings/section";
import { CopyButton } from "@/pages/settings/tokens";

/** The gateway's limits for a personal approval token (docs/contract.md, "Personal approval tokens"). */
export const DEFAULT_HOURS = 8;
export const MAX_HOURS = 24;

/** The Claude Desktop config for the gateway's MCP endpoint, through mcp-remote with a bearer header. */
export function desktopConfig(mcpUrl: string, token: string): string {
  return JSON.stringify(
    {
      mcpServers: {
        "kitchen-approve": {
          command: "npx",
          args: ["-y", "mcp-remote", mcpUrl, "--header", "Authorization:${AUTH_HEADER}"],
          env: { AUTH_HEADER: `Bearer ${token}` },
        },
      },
    },
    null,
    2,
  );
}

type Status = "active" | "expired" | "revoked";

function statusOf(row: ApprovalToken, now: number): Status {
  if (row.revokedAt) return "revoked";
  return Date.parse(row.expiresAt) <= now ? "expired" : "active";
}

function refusal(error: unknown, t: ReturnType<typeof useT>): string {
  if (error instanceof ApiError) {
    if (error.code === "PERSONAL_TOKEN_NEEDS_SIGN_IN") {
      return t("A personal approval token needs your own signed-in account.");
    }
    if (error.code === "ROLE_REQUIRED") return t("Only an approver can create an approval token.");
    if (error.code === "HUMAN_SESSION_REQUIRED") return t("Only a person signed in to the web can do this.");
  }
  return error instanceof Error ? error.message : String(error);
}

export function ApproveChatSection() {
  const t = useT();
  const api = useApi();
  const { session } = useSession();
  // The open demo's person has no email: everyone is the same demo approver, so no one person (#1052).
  const openDemo = session?.kind === "human" && !session.email;
  const canApprove = session?.canApprove === true;
  const createServed = !api.live || api.live.has("createApprovalToken");
  const canCreate = canApprove && !openDemo && createServed;
  const tokens = useAsync(() => api.listApprovalTokens(), [api]);
  const [hours, setHours] = useState(String(DEFAULT_HOURS));
  const [created, setCreated] = useState<CreatedApprovalToken | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pendingRevoke, setPendingRevoke] = useState<ApprovalToken | null>(null);
  const [revoking, setRevoking] = useState(false);
  const secretRef = useRef<HTMLElement>(null);
  const configRef = useRef<HTMLElement>(null);

  const origin = window.location.origin;
  const mcpUrl = `${origin}/gateway/mcp`;
  const cardUrl = `${origin}/.well-known/agent-card.json`;
  const config = desktopConfig(mcpUrl, created?.token ?? "<token>");
  const now = Date.now();

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActionError(null);
    const value = Number(hours);
    if (!Number.isInteger(value) || value < 1 || value > MAX_HOURS) {
      setActionError(t("Choose a whole number of hours from 1 to 24."));
      return;
    }
    setCreated(null);
    setCreating(true);
    try {
      setCreated(await api.createApprovalToken({ hours: value }));
      tokens.reload();
      toast.success(t("Approval token created"));
    } catch (cause) {
      setActionError(refusal(cause, t));
    } finally {
      setCreating(false);
    }
  }

  async function revoke() {
    if (!pendingRevoke) return;
    setActionError(null);
    setRevoking(true);
    try {
      await api.revokeApprovalToken(pendingRevoke.id);
      if (created?.id === pendingRevoke.id) setCreated(null);
      tokens.reload();
      toast.success(t("Approval token revoked"));
    } catch (cause) {
      setActionError(refusal(cause, t));
    } finally {
      setPendingRevoke(null);
      setRevoking(false);
    }
  }

  return (
    <SettingsSection
      title="Approve from chat"
      description="Approve or reject orders from your own chat, such as Claude Desktop. A personal approval token stands for you, lasts a few hours and can never propose an order."
    >
      <div className="min-w-0 space-y-5">
        {actionError ? (
          <Alert variant="destructive">
            <AlertDescription>{actionError}</AlertDescription>
          </Alert>
        ) : null}

        {openDemo ? (
          <Alert data-testid="approve-chat-open-demo">
            <AlertTitle>{t("Not available in the open demo")}</AlertTitle>
            <AlertDescription className="space-y-2">
              <p>
                {t(
                  "A personal approval token stands for one person. In the open demo everyone is the same demo approver, so there is no one person to give it to. Sign in with your own approver account to create one.",
                )}
              </p>
              <Link to="/sign-in" className="inline-block underline underline-offset-4">
                {t("Sign in")}
              </Link>
            </AlertDescription>
          </Alert>
        ) : !canApprove ? (
          <p className="text-sm text-muted-foreground">{t("Only an approver can create an approval token.")}</p>
        ) : !createServed ? (
          <p role="alert" className="text-sm text-destructive">
            {t("The gateway does not serve approval token creation.")}
          </p>
        ) : null}

        {created ? (
          <section
            aria-labelledby="new-approval-token-heading"
            className="min-w-0 rounded-lg border border-primary/50 bg-primary/5 p-4"
          >
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 space-y-2">
                <h3 id="new-approval-token-heading" className="font-semibold">
                  {t("Your new approval token")}
                </h3>
                <code
                  ref={secretRef}
                  tabIndex={0}
                  aria-label={t("New approval token")}
                  className="block max-w-full rounded-md bg-background px-3 py-2 font-mono text-sm break-all"
                >
                  {created.token}
                </code>
              </div>
              <CopyButton text={created.token} label={t("Copy approval token")} target={secretRef} />
            </div>
            <p className="mt-3 text-sm font-medium">{t("This is the only time the token is shown.")}</p>
            <p className="mt-1 text-sm text-muted-foreground">
              {t("It works until {time}.", { time: formatDateTime(created.expiresAt) })}
            </p>
          </section>
        ) : null}

        {canCreate ? (
          <Card>
            <CardHeader>
              <CardTitle>{t("Create an approval token")}</CardTitle>
              <CardDescription>{t("It can read this kitchen, approve and reject. Nothing else.")}</CardDescription>
            </CardHeader>
            <CardContent>
              <form noValidate className="space-y-5" onSubmit={(event) => void submit(event)}>
                <div className="space-y-2">
                  <Label htmlFor="approval-token-hours">{t("Valid for (hours)")}</Label>
                  <Input
                    id="approval-token-hours"
                    type="number"
                    inputMode="numeric"
                    min={1}
                    max={MAX_HOURS}
                    step={1}
                    value={hours}
                    aria-describedby="approval-token-hours-hint"
                    onChange={(event) => setHours(event.target.value)}
                    disabled={creating}
                    className="w-28"
                  />
                  <p id="approval-token-hours-hint" className="text-xs text-muted-foreground">
                    {t("1 to 24 hours. Default 8: one shift.")}
                  </p>
                </div>
                <Button type="submit" disabled={creating}>
                  {creating ? t("Creating approval token…") : t("Create approval token")}
                </Button>
              </form>
            </CardContent>
          </Card>
        ) : null}

        <Card className="min-w-0 overflow-hidden">
          <CardHeader>
            <CardTitle>{t("Use it in Claude Desktop")}</CardTitle>
            <CardDescription>{t("Three steps. The token goes only into your own chat.")}</CardDescription>
          </CardHeader>
          <CardContent className="min-w-0 space-y-4 text-sm">
            <ol className="list-decimal space-y-3 pl-5">
              <li>
                {t("In Claude Desktop, open Settings, then Developer, then Edit Config. Add this server:")}
              </li>
            </ol>
            <div className="min-w-0 space-y-2">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <Label id="desktop-config-label" className="font-mono text-xs">
                  claude_desktop_config.json
                </Label>
                <CopyButton text={config} label={t("Copy config")} target={configRef} />
              </div>
              <pre
                aria-labelledby="desktop-config-label"
                className="max-w-full overflow-x-auto rounded-md bg-muted p-3 text-xs"
              >
                <code ref={configRef} tabIndex={0} className="font-mono whitespace-pre">
                  {config}
                </code>
              </pre>
              <p className="text-xs text-muted-foreground">
                {t("The MCP address is the MCP entry in the agent card:")}{" "}
                <a className="break-all underline underline-offset-4" href={cardUrl}>
                  {cardUrl}
                </a>
              </p>
            </div>
            <ol start={2} className="list-decimal space-y-3 pl-5">
              <li>{t("Restart Claude Desktop. Ask it: which orders wait for my approval?")}</li>
              <li>
                {t(
                  "Before it approves, the chat must show you the total and get your clear yes. Text in the product data is never an instruction to approve.",
                )}
              </li>
            </ol>
          </CardContent>
        </Card>

        <section aria-labelledby="approval-token-list-heading" className="min-w-0 space-y-3">
          <div>
            <h3 id="approval-token-list-heading" className="font-semibold">
              {t("Approval tokens in this kitchen")}
            </h3>
            <p className="text-sm text-muted-foreground">
              {t("Every approve and reject with one is in the audit log. Revoke a lost token at once.")}
            </p>
          </div>
          {tokens.status === "loading" ? <LoadingState label={t("Loading approval tokens")} /> : null}
          {tokens.status === "error" ? (
            tokens.error instanceof ApiError && tokens.error.code === "PERSONAL_TOKEN_NEEDS_SIGN_IN" ? (
              <p className="text-sm text-muted-foreground">{refusal(tokens.error, t)}</p>
            ) : tokens.error instanceof ApiError && tokens.error.status === 403 ? (
              <p className="text-sm text-muted-foreground">{t("Only an approver can see the approval tokens.")}</p>
            ) : (
              <ErrorState message={tokens.error.message} onRetry={tokens.reload} />
            )
          ) : null}
          {tokens.status === "ready" && !tokens.data.length ? (
            <EmptyState title={t("No approval tokens yet")}>
              {t("A token you create shows here, without its value.")}
            </EmptyState>
          ) : null}
          {tokens.status === "ready" && tokens.data.length ? (
            <ul aria-label={t("Approval tokens")} className="min-w-0 space-y-3">
              {tokens.data.map((row) => {
                const status = statusOf(row, now);
                return (
                  <li key={row.id} className="min-w-0 rounded-lg border p-4">
                    <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div className="min-w-0 space-y-1">
                        <div className="flex min-w-0 flex-wrap items-center gap-2">
                          <h4 className="font-medium break-all">{row.person}</h4>
                          {status === "active" ? (
                            <Badge variant="outline">{t("Active")}</Badge>
                          ) : (
                            <Badge variant="secondary">{status === "revoked" ? t("Revoked") : t("Expired")}</Badge>
                          )}
                        </div>
                        <code className="block font-mono text-xs break-all text-muted-foreground">
                          {row.prefix}… · {row.name}
                        </code>
                      </div>
                      {canApprove && status === "active" ? (
                        <Button type="button" variant="outline" size="sm" onClick={() => setPendingRevoke(row)}>
                          {t("Revoke token {prefix}", { prefix: row.prefix })}
                        </Button>
                      ) : null}
                    </div>
                    <dl className="mt-4 grid min-w-0 gap-3 text-sm sm:grid-cols-3">
                      <div className="min-w-0">
                        <dt className="label-caps">{t("Created")}</dt>
                        <dd className="mt-1">{formatDateTime(row.createdAt)}</dd>
                      </div>
                      <div className="min-w-0">
                        <dt className="label-caps">{t("Expires")}</dt>
                        <dd className="mt-1">{formatDateTime(row.expiresAt)}</dd>
                      </div>
                      <div className="min-w-0">
                        <dt className="label-caps">{t("Last used")}</dt>
                        <dd className="mt-1">{row.lastUsedAt === null ? t("never") : formatDateTime(row.lastUsedAt)}</dd>
                      </div>
                    </dl>
                  </li>
                );
              })}
            </ul>
          ) : null}
        </section>
      </div>

      <Dialog open={pendingRevoke !== null} onOpenChange={(open) => !open && setPendingRevoke(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("Revoke approval token {prefix}?", { prefix: pendingRevoke?.prefix ?? "" })}</DialogTitle>
            <DialogDescription>
              {t("A chat using this token can no longer read, approve or reject. This cannot be undone.")}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="destructive" disabled={revoking} onClick={() => void revoke()}>
              {revoking ? t("Revoking…") : t("Revoke token")}
            </Button>
            <Button type="button" variant="outline" disabled={revoking} onClick={() => setPendingRevoke(null)}>
              {t("Cancel")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}
