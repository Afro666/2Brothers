import { Link } from "@tanstack/react-router";
import { ArrowRight, Ban, Bot, UserCheck, type LucideIcon } from "lucide-react";

import { useApi } from "@/api";
import { KIND_META } from "@/components/purchasing/audit-timeline";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { formatNumber, formatPercent } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import { cn } from "@/lib/utils";
import { SettingsSection } from "@/pages/settings/section";
import type { BuyerPermissions } from "@/types";

const GROUPS: { key: keyof BuyerPermissions; title: string; description: string; icon: LucideIcon; tone: string }[] = [
  {
    key: "alone",
    title: "The Buyer does alone",
    description: "No sign-off needed. Every step is written to the audit log.",
    icon: Bot,
    tone: "text-muted-foreground",
  },
  {
    key: "person",
    title: "A person signs off",
    description: "The Buyer prepares it and waits. Nothing happens until a person decides.",
    icon: UserCheck,
    tone: "text-primary",
  },
  {
    key: "never",
    title: "The Buyer can never",
    description: "The gateway refuses these from the Buyer, whatever it is asked.",
    icon: Ban,
    tone: "text-destructive",
  },
];

export function PermissionsSection() {
  const api = useApi();
  const permissions = useAsync(() => api.getPermissions(), [api]);
  const learning = useAsync(() => api.getAutoApproveLearning(), [api]);

  return (
    <SettingsSection
      title="Permissions"
      description="What the Buyer decides alone, what a person signs off, and what the Buyer can never do. Each row opens the audit log on the matching steps."
    >
      {permissions.status === "loading" ? <LoadingState label="Loading permissions" /> : null}
      {permissions.status === "error" ? (
        <ErrorState message={permissions.error.message} onRetry={permissions.reload} />
      ) : null}
      {permissions.status === "ready" ? (
        <div className="grid gap-4 xl:grid-cols-3">
          {GROUPS.map(({ key, title, description, icon: Icon, tone }) => (
            <Card key={key} className="gap-3">
              <CardHeader>
                <h3 id={`permissions-${key}`} className="flex items-center gap-2 leading-none font-semibold">
                  <Icon className={cn("size-4 shrink-0", tone)} aria-hidden />
                  {title}
                </h3>
                <CardDescription>{description}</CardDescription>
              </CardHeader>
              <CardContent>
                <ul aria-labelledby={`permissions-${key}`} className="divide-y">
                  {permissions.data[key].map((row) => (
                    <li key={row.action}>
                      <Link
                        to="/audit"
                        search={{ kind: row.auditKind } as never}
                        className="group flex min-h-11 flex-col justify-center gap-0.5 rounded-md py-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70"
                      >
                        <span className="font-medium group-hover:underline">{row.action}</span>
                        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                          Audit log: {KIND_META[row.auditKind].label}
                          <ArrowRight className="size-3" aria-hidden />
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          ))}
        </div>
      ) : null}

      <Card className="gap-4">
        <CardHeader>
          <div className="flex items-start justify-between gap-4">
            <h3 id="auto-approve-label" className="leading-snug font-semibold">
              Auto-approve small routine orders
            </h3>
            {/* Shows the state only: always off, always disabled, no handler. A person approves every order. */}
            <button
              type="button"
              role="switch"
              aria-checked={false}
              aria-labelledby="auto-approve-label"
              aria-describedby="auto-approve-locked auto-approve-note"
              disabled
              className="inline-flex h-6 w-11 shrink-0 cursor-not-allowed items-center rounded-full border bg-muted p-0.5 opacity-60"
            >
              <span className="size-4.5 rounded-full bg-background shadow-sm ring-1 ring-border" />
            </button>
          </div>
          <CardDescription id="auto-approve-note">
            Let the Buyer learn your kitchen first. After about 4 weeks of your approvals and corrections it can approve
            routine orders under your limit. Substitutes, unknown stock, allergens and anything over budget always come
            to you.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p id="auto-approve-locked" className="text-sm font-medium">
            Off. It unlocks after the learning period and is not available yet: a person approves every order.
          </p>
          {learning.status === "loading" ? <LoadingState label="Loading learning progress" /> : null}
          {learning.status === "error" ? (
            <ErrorState message={learning.error.message} onRetry={learning.reload} />
          ) : null}
          {learning.status === "ready" ? (
            <dl aria-label="Learning progress" className="grid gap-3 text-sm sm:grid-cols-3">
              {[
                {
                  term: "Weeks",
                  value: `${formatNumber(learning.data.weeks)} of ${formatNumber(learning.data.weeksNeeded)}`,
                },
                {
                  term: "Decisions",
                  value: `${formatNumber(learning.data.decisions)} of ${formatNumber(learning.data.decisionsNeeded)}`,
                },
                {
                  term: "Edit rate",
                  value: `${formatPercent(learning.data.editRate)} (needs ${formatPercent(learning.data.maxEditRate)} or less)`,
                },
              ].map(({ term, value }) => (
                <div key={term} className="rounded-lg border px-3 py-2">
                  <dt className="text-xs text-muted-foreground">{term}</dt>
                  <dd className="font-medium tabular-nums">{value}</dd>
                </div>
              ))}
            </dl>
          ) : null}
        </CardContent>
      </Card>
    </SettingsSection>
  );
}
