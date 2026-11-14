import { type FormEvent, type RefObject, useRef, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import { ApiError, type ApiToken, type ApiTokenScope, type CreatedApiToken } from "@/api/types";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
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
import { useAsync } from "@/lib/use-async";
import { useSession } from "@/lib/session";
import { SettingsSection } from "@/pages/settings/section";

const SCOPES: { value: ApiTokenScope; title: string; description: string }[] = [
  { value: "kitchen:read", title: "Read kitchen", description: "Read stock, menus and orders." },
  { value: "kitchen:propose", title: "Propose orders", description: "Use the Buyer agent and MCP tools to propose." },
  { value: "kitchen:write", title: "Update kitchen data", description: "Update stock, menus, recipes and suppliers." },
];

function permissionDenied(error: Error | null): boolean {
  return (
    error instanceof ApiError &&
    (error.status === 403 || error.code === "ROLE_REQUIRED" || error.code === "HUMAN_SESSION_REQUIRED")
  );
}

function selectText(element: HTMLElement | null) {
  if (!element) return;
  const selection = window.getSelection();
  const range = document.createRange();
  range.selectNodeContents(element);
  selection?.removeAllRanges();
  selection?.addRange(range);
  element.focus();
}

async function copyText(text: string, element: HTMLElement | null) {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      toast.success("Copied to clipboard");
      return;
    }
  } catch {}
  selectText(element);
  toast.success("Text selected. Use your device's copy command.");
}

// The ref, not its value: the element exists only after the first render.
function CopyButton({ text, label, target }: { text: string; label: string; target: RefObject<HTMLElement | null> }) {
  return (
    <Button type="button" variant="outline" size="sm" onClick={() => void copyText(text, target.current)}>
      {label}
    </Button>
  );
}

export function TokensSection() {
  const api = useApi();
  const { session } = useSession();
  // Unknown is not permission: only an account the gateway says may approve manages tokens.
  const canManage = session?.canApprove === true;
  const tokens = useAsync(() => api.listApiTokens(), [api]);
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<ApiTokenScope[]>(["kitchen:read", "kitchen:propose"]);
  const [created, setCreated] = useState<CreatedApiToken | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [pendingRevoke, setPendingRevoke] = useState<ApiToken | null>(null);
  const [revoking, setRevoking] = useState(false);
  const secretRef = useRef<HTMLElement>(null);
  const mcpRef = useRef<HTMLElement>(null);
  const curlRef = useRef<HTMLElement>(null);

  const origin = window.location.origin;
  const kitchenId = import.meta.env.VITE_GATEWAY_KITCHEN_ID || "demo-kitchen";
  const token = created?.token ?? "<token>";
  const mcpCommand = `claude mcp add --transport http kitchen-buyer ${origin}/gateway/mcp --header "Authorization: Bearer ${token}"`;
  const curlCommand = `curl -H "Authorization: Bearer ${token}" ${origin}/gateway/v1/kitchens/${encodeURIComponent(kitchenId)}/proposals`;

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setActionError(null);
    const trimmed = name.trim();
    if (!trimmed || trimmed.length > 80) {
      setActionError("Enter a token name between 1 and 80 characters.");
      return;
    }
    if (!scopes.length) {
      setActionError("Select at least one token scope.");
      return;
    }
    setCreated(null);
    setCreating(true);
    try {
      const next = await api.createApiToken({ name: trimmed, scopes });
      setCreated(next);
      setName("");
      tokens.reload();
      toast.success("Token created");
    } catch (cause) {
      setActionError(
        cause instanceof ApiError && permissionDenied(cause)
          ? "Only a signed-in approver can manage API tokens."
          : cause instanceof Error
            ? cause.message
            : String(cause),
      );
    } finally {
      setCreating(false);
    }
  }

  async function revoke() {
    if (!pendingRevoke) return;
    setActionError(null);
    setRevoking(true);
    try {
      await api.revokeApiToken(pendingRevoke.id);
      setPendingRevoke(null);
      tokens.reload();
      toast.success("Token revoked");
    } catch (cause) {
      setPendingRevoke(null);
      setActionError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setRevoking(false);
    }
  }

  return (
    <SettingsSection
      title="API & MCP tokens"
      description="A token lets an agent or script read this kitchen, propose orders, and optionally update kitchen data. It can never approve."
    >
      <div className="min-w-0 space-y-5">
        <p className="max-w-prose text-sm text-muted-foreground">
          Tokens cannot have <code className="font-mono">kitchen:approve</code>: only a signed-in person approves.
        </p>

        {actionError ? (
          <Alert variant="destructive">
            <AlertDescription>{actionError}</AlertDescription>
          </Alert>
        ) : null}

        {created ? (
          <section
            aria-labelledby="new-token-heading"
            className="min-w-0 rounded-lg border border-primary/50 bg-primary/5 p-4"
          >
            <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="min-w-0 space-y-2">
                <h3 id="new-token-heading" className="font-semibold">
                  Your new API token
                </h3>
                <code
                  ref={secretRef}
                  tabIndex={0}
                  aria-label="New API token"
                  className="block max-w-full rounded-md bg-background px-3 py-2 font-mono text-sm break-all"
                >
                  {created.token}
                </code>
              </div>
              <CopyButton text={created.token} label="Copy token" target={secretRef} />
            </div>
            <p className="mt-3 text-sm font-medium">This is the only time the token is shown.</p>
          </section>
        ) : null}

        {canManage ? (
          <Card>
            <CardHeader>
              <CardTitle>Create a token</CardTitle>
              <CardDescription>Give every agent or integration its own revocable token.</CardDescription>
            </CardHeader>
            <CardContent>
              <form noValidate className="space-y-5" onSubmit={(event) => void submit(event)}>
                <div className="space-y-2">
                  <Label htmlFor="token-name">Token name</Label>
                  <Input
                    id="token-name"
                    value={name}
                    required
                    aria-describedby="token-name-hint"
                    onChange={(event) => setName(event.target.value)}
                    disabled={creating}
                    autoComplete="off"
                  />
                  <p id="token-name-hint" className="text-xs text-muted-foreground">
                    1 to 80 characters.
                  </p>
                </div>
                <fieldset className="space-y-3">
                  <legend className="label-caps mb-2">Scopes</legend>
                  {SCOPES.map((scope) => (
                    <div key={scope.value} className="flex items-start gap-3">
                      <Checkbox
                        id={`token-scope-${scope.value.split(":")[1]}`}
                        checked={scopes.includes(scope.value)}
                        disabled={creating}
                        aria-describedby={`token-scope-${scope.value.split(":")[1]}-description`}
                        onCheckedChange={(checked) =>
                          setScopes((previous) =>
                            checked === true
                              ? [...previous, scope.value]
                              : previous.filter((value) => value !== scope.value),
                          )
                        }
                      />
                      <div className="min-w-0 space-y-1">
                        <Label
                          htmlFor={`token-scope-${scope.value.split(":")[1]}`}
                          className="inline-flex flex-wrap items-center gap-2"
                        >
                          {scope.title}
                          <code className="font-mono text-xs text-muted-foreground">{scope.value}</code>
                        </Label>
                        <p
                          id={`token-scope-${scope.value.split(":")[1]}-description`}
                          className="text-xs text-muted-foreground"
                        >
                          {scope.description}
                        </p>
                      </div>
                    </div>
                  ))}
                </fieldset>
                <Button type="submit" disabled={creating}>
                  {creating ? "Creating token…" : "Create token"}
                </Button>
              </form>
            </CardContent>
          </Card>
        ) : (
          <p className="text-sm text-muted-foreground">Only an approver can create or revoke API tokens.</p>
        )}

        <section aria-labelledby="token-list-heading" className="min-w-0 space-y-3">
          <div>
            <h3 id="token-list-heading" className="font-semibold">
              Your tokens
            </h3>
            <p className="text-sm text-muted-foreground">Secrets are never shown again after creation.</p>
          </div>
          {tokens.status === "loading" ? <LoadingState label="Loading API tokens" /> : null}
          {tokens.status === "error" ? (
            permissionDenied(tokens.error) ? (
              <p className="text-sm text-muted-foreground">Your account does not have permission to view API tokens.</p>
            ) : (
              <ErrorState message={tokens.error.message} onRetry={tokens.reload} />
            )
          ) : null}
          {tokens.status === "ready" && !tokens.data.length ? (
            <EmptyState title="No tokens yet">Create a token to connect your own agent.</EmptyState>
          ) : null}
          {tokens.status === "ready" && tokens.data.length ? (
            <ul aria-label="API tokens" className="min-w-0 space-y-3">
              {tokens.data.map((row) => (
                <li key={row.id} className="min-w-0 rounded-lg border p-4">
                  <div className="flex min-w-0 flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                    <div className="min-w-0 space-y-1">
                      <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <h4 className="font-medium break-words">{row.name}</h4>
                        {row.revokedAt ? (
                          <Badge variant="secondary">Revoked</Badge>
                        ) : (
                          <Badge variant="outline">Active</Badge>
                        )}
                      </div>
                      <code className="block font-mono text-xs break-all text-muted-foreground">{row.prefix}…</code>
                    </div>
                    {canManage && !row.revokedAt ? (
                      <Button type="button" variant="outline" size="sm" onClick={() => setPendingRevoke(row)}>
                        Revoke {row.name}
                      </Button>
                    ) : null}
                  </div>
                  <dl className="mt-4 grid min-w-0 gap-3 text-sm sm:grid-cols-3">
                    <div className="min-w-0">
                      <dt className="label-caps">Scopes</dt>
                      <dd className="mt-1 flex flex-wrap gap-1">
                        {row.scopes.map((scope) => (
                          <code key={scope} className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs break-all">
                            {scope}
                          </code>
                        ))}
                      </dd>
                    </div>
                    <div className="min-w-0">
                      <dt className="label-caps">Created</dt>
                      <dd className="mt-1">{formatDateTime(row.createdAt)}</dd>
                    </div>
                    <div className="min-w-0">
                      <dt className="label-caps">Last used</dt>
                      <dd className="mt-1">
                        {row.lastUsedAt === undefined
                          ? "unknown"
                          : row.lastUsedAt === null
                            ? "never"
                            : formatDateTime(row.lastUsedAt)}
                      </dd>
                    </div>
                  </dl>
                </li>
              ))}
            </ul>
          ) : null}
        </section>

        <Card className="min-w-0 overflow-hidden">
          <CardHeader>
            <CardTitle>Connect your own agent</CardTitle>
            <CardDescription>
              Use <code className="font-mono">kitchen:propose</code> for MCP tools and proposals.
            </CardDescription>
          </CardHeader>
          <CardContent className="min-w-0 space-y-5">
            <div className="min-w-0 space-y-2">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <Label id="mcp-command-label" className="label-caps">
                  MCP: Claude Code
                </Label>
                <CopyButton text={mcpCommand} label="Copy MCP command" target={mcpRef} />
              </div>
              <pre
                aria-labelledby="mcp-command-label"
                className="max-w-full overflow-x-auto rounded-md bg-muted p-3 text-xs"
              >
                <code ref={mcpRef} tabIndex={0} className="font-mono whitespace-pre">
                  {mcpCommand}
                </code>
              </pre>
            </div>
            <div className="min-w-0 space-y-2">
              <div className="flex min-w-0 flex-wrap items-center justify-between gap-2">
                <Label id="curl-command-label" className="label-caps">
                  HTTP: list proposals (needs kitchen:read)
                </Label>
                <CopyButton text={curlCommand} label="Copy curl command" target={curlRef} />
              </div>
              <pre
                aria-labelledby="curl-command-label"
                className="max-w-full overflow-x-auto rounded-md bg-muted p-3 text-xs"
              >
                <code ref={curlRef} tabIndex={0} className="font-mono whitespace-pre">
                  {curlCommand}
                </code>
              </pre>
            </div>
            <div className="flex min-w-0 flex-col gap-2 text-sm">
              <a className="break-all underline underline-offset-4" href={`${origin}/llms.txt`}>
                Agent instructions: {origin}/llms.txt
              </a>
              <a className="break-all underline underline-offset-4" href={`${origin}/.well-known/agent-card.json`}>
                Agent card: {origin}/.well-known/agent-card.json
              </a>
            </div>
          </CardContent>
        </Card>
      </div>

      <Dialog open={pendingRevoke !== null} onOpenChange={(open) => !open && setPendingRevoke(null)}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Revoke {pendingRevoke?.name || "API token"}?</DialogTitle>
            <DialogDescription>
              Agents using this token will immediately lose access. This cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button type="button" variant="destructive" disabled={revoking} onClick={() => void revoke()}>
              {revoking ? "Revoking…" : "Revoke token"}
            </Button>
            <Button type="button" variant="outline" disabled={revoking} onClick={() => setPendingRevoke(null)}>
              Cancel
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </SettingsSection>
  );
}
