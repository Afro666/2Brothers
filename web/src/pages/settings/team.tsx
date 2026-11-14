import { useApi } from "@/api";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { SampleData } from "@/components/purchasing/sample-data";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { useAsync } from "@/lib/use-async";
import { SettingsSection } from "@/pages/settings/section";

const ROLE_DETAILS = {
  approver: "Can request, approve and reject orders.",
  chef: "Can request orders; cannot approve them.",
  viewer: "Read only; cannot request or approve orders.",
} as const;

export function TeamSection() {
  const api = useApi();
  const state = useAsync(() => api.listTeamMembers(), [api]);

  return (
    <SettingsSection title="Team" description="People in this kitchen and the work their role allows. Only approvers can approve orders.">
      <SampleData of="listTeamMembers" />
      {state.status === "loading" ? <LoadingState label="Loading team" /> : null}
      {state.status === "error" ? <ErrorState message={state.error.message} onRetry={state.reload} /> : null}
      {state.status === "ready" && state.data.length === 0 ? <EmptyState title="No team members">The gateway returned no members for this kitchen.</EmptyState> : null}
      {state.status === "ready" && state.data.length > 0 ? (
        <Card>
          <CardHeader>
            <CardTitle>Members and roles</CardTitle>
            <CardDescription>Roles are managed by the gateway. This list is read-only.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="divide-y" aria-label="Kitchen team members">
              {state.data.map((member) => (
                <li key={member.id} className="flex flex-col gap-2 py-4 first:pt-0 last:pb-0 sm:flex-row sm:items-center sm:justify-between">
                  <div className="min-w-0">
                    <p className="font-medium">{member.name}</p>
                    <p className="truncate text-sm text-muted-foreground">{member.email}</p>
                    <p className="mt-1 text-sm text-muted-foreground">{ROLE_DETAILS[member.role]}</p>
                  </div>
                  <Badge variant={member.role === "approver" ? "default" : "outline"} className="capitalize">{member.role}</Badge>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      ) : null}
    </SettingsSection>
  );
}
