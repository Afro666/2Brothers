import { Link } from "@tanstack/react-router";
import { ArrowRight, Ban, Bot, UserCheck, type LucideIcon } from "lucide-react";

import { useApi } from "@/api";
import { KIND_META } from "@/components/purchasing/audit-timeline";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Card, CardContent, CardDescription, CardHeader } from "@/components/ui/card";
import { formatNumber, formatPercent } from "@/lib/format";
import { useAsync } from "@/lib/use-async";
import { useT, type TranslationVariables } from "@/lib/i18n";
import { cn } from "@/lib/utils";
import { SampleData } from "@/components/purchasing/sample-data";
import { SettingsSection } from "@/pages/settings/section";
import type { BuyerPermissions } from "@/types";

/** The rows the gateway sends (gateway/permissions.py), so the coverage test sees their Finnish. */
export const PERMISSION_ACTIONS = [
  "Search the catalog",
  "Compare price, reliability and carbon",
  "Choose products",
  "Size quantities",
  "Split an order",
  "Refuse unsafe lines",
  "Ask for approval",
  "Every order",
  "Every order that is not routine",
  "Any substitute",
  "Standing-order changes",
  "Sharing forecasts",
  "API tokens and webhooks",
  "Approve from your own chat",
  "Approve or reject an order",
  "Approve with the same token or session that proposed it",
  "Place an order nobody approved",
  "Cancel an order",
  "Change a quantity",
  "Act for another kitchen",
  "Approve routine orders up to {limit} EUR",
] as const;

/** The gateway's auto-approve row (gateway/permissions.py) sits in `alone`; the Buyer never approves. */
const AUTO_APPROVE_ROW = /^Approve routine orders up to (.+) EUR$/;

/** A gateway row through the dictionary; a row not listed above is shown as sent (t() does that). */
export function permissionText(action: string, t: (text: string, vars?: TranslationVariables) => string) {
  const limit = AUTO_APPROVE_ROW.exec(action);
  if (limit) return t("Approve routine orders up to {limit} EUR", { limit: limit[1] });
  if (action === "Approve with the credential that proposed") return t("Approve with the same token or session that proposed it");
  // The catalog's field label uses the same text, so both share one Finnish entry ("Hae tuoteluettelosta").
  if (action === "Search the catalog") return t("Search the catalog");
  return t(action);
}

export const GROUPS: { key: keyof BuyerPermissions; title: string; description: string; icon: LucideIcon; tone: string }[] = [
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
  const t = useT();
  const api = useApi();
  const permissions = useAsync(() => api.getPermissions(), [api]);
  const learning = useAsync(() => api.getAutoApproveLearning(), [api]);

  return (
    <SettingsSection
      title="Permissions"
      description="What the Buyer decides alone, what a person signs off, and what the Buyer can never do. Each row opens the audit log on the matching steps."
    >
      <SampleData of="getPermissions" />
      {permissions.status === "loading" ? <LoadingState label={t("Loading permissions")} /> : null}
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
                  {t(title)}
                </h3>
                <CardDescription>{t(description)}</CardDescription>
              </CardHeader>
              <CardContent>
                <ul aria-labelledby={`permissions-${key}`} className="divide-y">
                  {/* #1844: auto-approve is not something the Buyer does: the card below says who approves. */}
                  {permissions.data[key]
                    .filter((row) => !(key === "alone" && AUTO_APPROVE_ROW.test(row.action)))
                    .map((row) => (
                    <li key={row.action}>
                      <Link
                        to="/audit"
                        search={{ kind: row.auditKind } as never}
                        className="group flex min-h-11 flex-col justify-center gap-0.5 rounded-md py-2 text-sm outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70"
                      >
                        <span className="font-medium group-hover:underline">{permissionText(row.action, t)}</span>
                        <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                          {t("Activity log: {kind}", { kind: t(KIND_META[row.auditKind].label) })}
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
              {t("Auto-approve small routine orders")}
            </h3>
            {/* Shows the state only: always off, always disabled, no handler. A person approves every order. */}
            <button
              type="button"
              role="switch"
              aria-checked={learning.status === "ready" && learning.data.enabled === true}
              aria-labelledby="auto-approve-label"
              aria-describedby="auto-approve-locked auto-approve-note"
              disabled
              className="inline-flex h-6 w-11 shrink-0 cursor-not-allowed items-center rounded-full border bg-muted p-0.5 opacity-60"
            >
              <span className="size-4.5 rounded-full bg-background shadow-sm ring-1 ring-border" />
            </button>
          </div>
          <CardDescription id="auto-approve-note">
            {t(
              "Let the Buyer learn your kitchen first. After about 4 weeks of your approvals and corrections, an approver can switch this on: the gateway then approves routine orders under the limit that person sets. The Buyer itself never approves. Substitutes, unknown stock, allergens and anything over budget always come to you.",
            )}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p id="auto-approve-locked" className="text-sm font-medium">
            {learning.status === "ready" && learning.data.enabled === true
              ? t(
                  "On{actor}. Routine orders{limit} are approved without waiting; every one is in the audit log. Everything else still comes to a person.",
                  {
                    actor: learning.data.setBy
                      ? t(", switched on by {name}", { name: learning.data.setBy })
                      : "",
                    limit: learning.data.limitEur ? t(" up to €{amount}", { amount: learning.data.limitEur }) : "",
                  },
                )
              : t("Off. It unlocks after the learning period and is not available yet: a person approves every order.")}
          </p>
          {learning.status === "loading" ? <LoadingState label={t("Loading learning progress")} /> : null}
          {learning.status === "error" ? (
            <ErrorState message={learning.error.message} onRetry={learning.reload} />
          ) : null}
          {learning.status === "ready" ? (
            <dl aria-label={t("Learning progress")} className="grid gap-3 text-sm sm:grid-cols-3">
              {[
                {
                  term: t("Weeks since your first decision"),
                  value: t("{value} of {needed}", {
                    value: formatNumber(learning.data.weeks),
                    needed: formatNumber(learning.data.weeksNeeded),
                  }),
                },
                {
                  term: t("Your decisions to approve or reject"),
                  value: t("{value} of {needed}", {
                    value: formatNumber(learning.data.decisions),
                    needed: formatNumber(learning.data.decisionsNeeded),
                  }),
                },
                {
                  term: t("Approved orders you edited before approving"),
                  value: t("{rate} (needs {maximum} or less)", {
                    rate: formatPercent(learning.data.editRate),
                    maximum: formatPercent(learning.data.maxEditRate),
                  }),
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

