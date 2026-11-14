import { type FormEvent, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import type { CreatedWebhook, WebhookDelivery } from "@/api/types";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { SampleData } from "@/components/purchasing/sample-data";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { formatDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useAsync } from "@/lib/use-async";
import { SettingsSection } from "@/pages/settings/section";

const DEFAULT_EVENTS = ["proposal.ready", "proposal.approved", "proposal.rejected", "order.placed", "total_mismatch", "recall.alert"];

function validWebhookUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "https:";
  } catch {
    return false;
  }
}

export function DeveloperSection() {
  const api = useApi();
  const { session } = useSession();
  const canManage = session?.canApprove === true;
  const hooks = useAsync(() => api.listWebhooks(), [api]);
  const health = useAsync(() => api.getGatewayHealth(), [api]);
  const calls = useAsync(() => api.listRecentApiCalls(), [api]);
  const [url, setUrl] = useState("");
  const [events, setEvents] = useState<string[]>(["proposal.ready", "recall.alert"]);
  const [created, setCreated] = useState<CreatedWebhook | null>(null);
  const [deliveries, setDeliveries] = useState<Record<string, WebhookDelivery>>({});
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [testing, setTesting] = useState<string | null>(null);
  const origin = window.location.origin;
  const version = import.meta.env.VITE_APP_VERSION || "unknown";
  const gitSha = import.meta.env.VITE_GIT_SHA || "unknown";
  const reportsHealth = api.live?.has("getGatewayHealth") === true;

  async function create(event: FormEvent) {
    event.preventDefault();
    const trimmed = url.trim();
    if (!validWebhookUrl(trimmed)) {
      setError("Enter an https webhook URL.");
      return;
    }
    if (events.length === 0) {
      setError("Select at least one webhook event.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const hook = await api.createWebhook({ url: trimmed, events }, "human");
      setCreated(hook);
      setUrl("");
      hooks.reload();
      toast.success("Webhook created");
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setCreating(false);
    }
  }

  async function test(id: string) {
    setTesting(id);
    setError(null);
    try {
      const delivery = await api.testWebhook(id, "human");
      setDeliveries((current) => ({ ...current, [id]: delivery }));
      if (delivery.ok) toast.success(`Webhook test delivered (${delivery.status ?? "unknown"})`);
      else setError(`Webhook test failed: ${delivery.error ?? `HTTP ${delivery.status ?? "unknown"}`}.`);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setTesting(null);
    }
  }

  return (
    <SettingsSection title="Developer" description="API documentation, signed event webhooks and status-only diagnostics. Request and response bodies are never shown.">
      <div className="flex flex-wrap gap-2" aria-label="Gateway status">
        <Badge variant="outline">Page data: {api.live && api.live.size > 0 ? "gateway" : "mock"}</Badge>
        <Badge variant="outline">Valio API: {health.status === "ready" ? health.data.valioMode : "unknown"}</Badge>
      </div>

      <div className="grid items-start gap-5 xl:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>API & build</CardTitle>
            <CardDescription>Interactive OpenAPI documentation served by the gateway.</CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <Button asChild variant="outline"><a href={`${origin}/api/docs`} target="_blank" rel="noreferrer">OpenAPI docs</a></Button>
            <dl className="grid gap-3 text-sm sm:grid-cols-2">
              <div><dt className="label-caps text-muted-foreground">App version</dt><dd className="font-mono break-all">{version}</dd></div>
              <div><dt className="label-caps text-muted-foreground">Git SHA</dt><dd className="font-mono break-all">{gitSha}</dd></div>
              <div><dt className="label-caps text-muted-foreground">Gateway health</dt><dd>{!reportsHealth ? "not connected (sample data)" : health.status === "ready" ? health.data.status : health.status === "error" ? "unknown" : "Loading…"}</dd></div>
            </dl>
            {health.status === "error" ? <ErrorState message={health.error.message} onRetry={health.reload} /> : null}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="flex flex-wrap items-center gap-2"><CardTitle>Recent API calls</CardTitle><SampleData of="listRecentApiCalls" /></div>
            <CardDescription>Method, route and HTTP status only; no request or response bodies.</CardDescription>
          </CardHeader>
          <CardContent>
            {calls.status === "loading" ? <LoadingState label="Loading recent API calls" /> : null}
            {calls.status === "error" ? <ErrorState message={calls.error.message} onRetry={calls.reload} /> : null}
            {calls.status === "ready" && calls.data.length === 0 ? <EmptyState title="No recent API calls" /> : null}
            {calls.status === "ready" && calls.data.length > 0 ? (
              <ul className="divide-y" aria-label="Recent API calls">
                {calls.data.map((call) => (
                  <li key={call.id} className="grid gap-1 py-3 first:pt-0 last:pb-0 sm:grid-cols-[1fr_auto] sm:items-center">
                    <div className="min-w-0"><p className="font-mono text-sm break-all"><span className="font-semibold">{call.method}</span> {call.path}</p><p className="text-xs text-muted-foreground">{formatDateTime(call.at)}</p></div>
                    <Badge variant={call.status !== null && call.status < 400 ? "outline" : "destructive"}>{call.status ?? "unknown"}</Badge>
                  </li>
                ))}
              </ul>
            ) : null}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Webhooks</CardTitle>
          <CardDescription>Send signed JSON events to an HTTPS endpoint. The signing secret is shown only once.</CardDescription>
        </CardHeader>
        <CardContent className="space-y-6">
          {error ? <p role="alert" className="text-sm text-destructive">{error}</p> : null}
          {created ? (
            <div className="rounded-md border bg-muted/40 p-4 space-y-2">
              <p className="font-medium">Webhook created — copy its secret now</p>
              <code className="block font-mono text-sm break-all">{created.secret}</code>
              <p className="text-sm text-muted-foreground">Verify the X-TKB-Signature header with this secret. It will not be shown again.</p>
            </div>
          ) : null}
          {canManage ? (
            <form className="space-y-4" onSubmit={(event) => void create(event)} noValidate>
              <div className="space-y-2"><Label htmlFor="webhook-url">Webhook URL</Label><Input id="webhook-url" type="url" placeholder="https://hooks.example.com/kitchen" value={url} disabled={creating} onChange={(event) => { setUrl(event.target.value); setError(null); }} /></div>
              <fieldset className="space-y-3"><legend className="mb-3 text-sm font-medium">Events</legend><div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {(hooks.status === "ready" ? hooks.data.events : DEFAULT_EVENTS).map((event) => (
                  <div key={event} className="flex items-center gap-2"><Checkbox id={`webhook-event-${event}`} checked={events.includes(event)} disabled={creating} onCheckedChange={(checked) => { setEvents((current) => checked === true ? [...new Set([...current, event])] : current.filter((item) => item !== event)); setError(null); }} /><Label htmlFor={`webhook-event-${event}`} className="font-mono text-xs font-normal">{event}</Label></div>
                ))}
              </div></fieldset>
              <Button type="submit" disabled={creating || hooks.status === "loading"}>{creating ? "Creating…" : "Create webhook"}</Button>
            </form>
          ) : <p className="text-sm text-muted-foreground">Only an approver can create or test webhooks.</p>}

          {hooks.status === "loading" ? <LoadingState label="Loading webhooks" /> : null}
          {hooks.status === "error" ? <ErrorState message={hooks.error.message} onRetry={hooks.reload} /> : null}
          {hooks.status === "ready" && hooks.data.webhooks.length === 0 ? <EmptyState title="No webhooks">Create one to receive kitchen events.</EmptyState> : null}
          {hooks.status === "ready" && hooks.data.webhooks.length > 0 ? (
            <ul className="divide-y" aria-label="Configured webhooks">
              {hooks.data.webhooks.map((hook) => {
                const delivery = deliveries[hook.id];
                return <li key={hook.id} className="space-y-3 py-4 first:pt-0 last:pb-0">
                  <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between"><div className="min-w-0"><p className="font-mono text-sm break-all">{hook.url}</p><p className="mt-1 text-xs text-muted-foreground">{hook.events.join(", ")}</p></div>{canManage ? <Button type="button" variant="outline" size="sm" disabled={testing !== null} onClick={() => void test(hook.id)}>{testing === hook.id ? "Sending…" : `Send test to ${hook.id}`}</Button> : null}</div>
                  {delivery ? <p className={delivery.ok ? "text-sm text-muted-foreground" : "text-sm text-destructive"}>Last test: {delivery.ok ? "delivered" : "failed"}, HTTP {delivery.status ?? "unknown"}, {delivery.attempts ?? "unknown"} attempt{delivery.attempts === 1 ? "" : "s"}.</p> : null}
                </li>;
              })}
            </ul>
          ) : null}
        </CardContent>
      </Card>
    </SettingsSection>
  );
}
