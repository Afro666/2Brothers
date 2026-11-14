import { Link, useNavigate, useSearch } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

import { useApi } from "@/api";
import { ApiError, type Draft, type KitchenNutrition } from "@/api/types";
import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogBody, DialogContent, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { useAsync } from "@/lib/use-async";
import { formatDate, formatEur, formatNumber } from "@/lib/format";
import { isoWeekOf, shiftWeek, weekDates } from "@/lib/week";
import type { DemandLine, MenuPlanEntry, PlanProposal, Recipe } from "@/types";
import { AppShell } from "@/components/purchasing/app-shell";
import { randomHex } from "@/lib/random-id";
import { getLanguage, useT } from "@/lib/i18n";

function todayIso(): string {
  const now = new Date();
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(
    2,
    "0",
  )}`;
}

/** Without `?week=` the planner opens on next week: that is the week a kitchen plans and orders for. */
function displayedWeek(week: string | undefined): string {
  return week ?? shiftWeek(isoWeekOf(todayIso()), 1);
}

function weekTitle(week: string, t: ReturnType<typeof useT>): string {
  const dates = weekDates(week);
  const from = new Date(`${dates[0]}T12:00:00Z`);
  const to = new Date(`${dates[6]}T12:00:00Z`);
  const locale = getLanguage() === "fi" ? "fi-FI" : "en-GB";
  const month = new Intl.DateTimeFormat(locale, { month: "short", timeZone: "UTC" });
  return t("Week {week}, {from} to {to} {month} {year}", {
    week: Number(week.slice(-2)),
    from: from.getUTCDate(),
    to: to.getUTCDate(),
    month: month.format(to),
    year: to.getUTCFullYear(),
  });
}

function weekday(date: string): string {
  return new Intl.DateTimeFormat(getLanguage() === "fi" ? "fi-FI" : "en-GB", { weekday: "long", timeZone: "UTC" }).format(new Date(`${date}T12:00:00Z`));
}

function dateRange(date: string): string {
  return formatDate(date);
}

function sameEntries(left: MenuPlanEntry[], right: MenuPlanEntry[]): boolean {
  return (
    left.length === right.length &&
    left.every((entry, index) => {
      const other = right[index];
      return (
        other &&
        entry.id === other.id &&
        entry.date === other.date &&
        entry.meal === other.meal &&
        entry.recipeId === other.recipeId &&
        entry.covers === other.covers
      );
    })
  );
}

function DemandList({ lines, dates }: { lines: DemandLine[]; dates: string[] }) {
  const t = useT();
  const products = new Map<string, DemandLine[]>();
  for (const line of lines) {
    const list = products.get(line.productId) ?? [];
    list.push(line);
    products.set(line.productId, list);
  }
  if (products.size === 0) {
    return <EmptyState title={t("No demand for this week")}>{t("Add menu entries to see what the kitchen needs.")}</EmptyState>;
  }

  return (
    <div className="space-y-3">
      {[...products.values()].map((productLines) => {
        const first = productLines[0];
        const total = productLines.reduce((sum, line) => sum + line.need, 0);
        return (
          <Card key={first.productId}>
            <CardContent className="space-y-2 pt-6">
              <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                <h3 className="font-medium">{first.productName}</h3>
                <p className="text-sm font-medium tabular-nums">
                  {t("{amount} {unit} total", { amount: formatNumber(total), unit: first.unit })}
                </p>
              </div>
              <ul className="space-y-1 text-sm tabular-nums text-muted-foreground">
                {dates.flatMap((date) =>
                  productLines
                    .filter((line) => line.date === date)
                    .map((line) => (
                      <li key={`${line.date}-${line.productId}`}>
                        <span className="font-medium text-foreground">{weekday(line.date)}:</span>{" "}
                        {formatNumber(line.need)} {line.unit} — {line.why}
                      </li>
                    )),
                )}
              </ul>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}

/**
 * The shown week's planned energy against what the approved orders for the week contain.
 * A number the gateway could not count is named as not known, never shown as 0.
 */
function EnergySummary({ nutrition }: { nutrition: KitchenNutrition }) {
  const t = useT();
  const { planned, ordered, orderedVsPlanned } = nutrition;
  const parts: string[] = [];
  if (nutrition.days.length === 0) parts.push(t("No energy planned for this week yet."));
  else if (planned.kcal == null) parts.push(t("Planned: energy not known."));
  else {
    parts.push(t("Planned: {kcal} kcal.", { kcal: formatNumber(planned.kcal) }));
    if (!planned.complete) parts.push(t("Partly counted: some ingredients have no nutrition table."));
  }
  if (ordered.lines === 0) parts.push(t("Nothing ordered for this week yet."));
  else if (ordered.kcal == null) parts.push(t("Ordered for this week so far: energy not known."));
  else {
    parts.push(
      orderedVsPlanned == null
        ? t("Ordered for this week so far: {kcal} kcal.", { kcal: formatNumber(ordered.kcal) })
        : t("Ordered for this week so far: {kcal} kcal ({percent}% of the plan).", {
            kcal: formatNumber(ordered.kcal),
            percent: formatNumber(Math.round(orderedVsPlanned * 100)),
          }),
    );
    if (ordered.knownLines < ordered.lines) {
      parts.push(
        t("Counted from {known} of {total} order lines.", {
          known: formatNumber(ordered.knownLines),
          total: formatNumber(ordered.lines),
        }),
      );
    }
  }
  return <p className="text-sm tabular-nums text-muted-foreground">{parts.join(" ")}</p>;
}

const products = (count: number, t: ReturnType<typeof useT>) =>
  count === 1 ? t("{count} product", { count: formatNumber(count) }) : t("{count} products", { count: formatNumber(count) });

/** What the proposal call answered, for the week it was asked for. */
type ProposeOutcome =
  | { week: string; kind: "proposal"; proposal: PlanProposal }
  | { week: string; kind: "nothing" }
  | { week: string; kind: "error"; message: string };

function ProposeMessage({ outcome }: { outcome: ProposeOutcome }) {
  const t = useT();
  if (outcome.kind === "nothing") return <p>{t("Stock covers this week's plan. Nothing to order.")}</p>;
  if (outcome.kind === "error") return <p className="text-destructive">{outcome.message}</p>;
  const { proposal } = outcome;
  const approvals = (
    <Link to="/approvals" className="font-medium text-primary underline underline-offset-4">
      {t("Orders > To approve")}
    </Link>
  );
  return (
    <div className="space-y-1">
      {proposal.status === "APPROVED" ? (
        <p>
          {proposal.lineCount === 1
            ? t("Order placed automatically: {count} line, {total}. See it in ", { count: formatNumber(proposal.lineCount), total: formatEur(proposal.totalInclVat) })
            : t("Order placed automatically: {count} lines, {total}. See it in ", { count: formatNumber(proposal.lineCount), total: formatEur(proposal.totalInclVat) })}
          <Link to="/orders" className="font-medium text-primary underline underline-offset-4">
            {t("Order history")}
          </Link>
          .
        </p>
      ) : proposal.status === "READY" ? (
        <p>
          {(proposal.lineCount === 1
            ? t("Proposal ready: {count} line, {total}. A person approves it in ", { count: formatNumber(proposal.lineCount), total: formatEur(proposal.totalInclVat) })
            : t("Proposal ready: {count} lines, {total}. A person approves it in ", { count: formatNumber(proposal.lineCount), total: formatEur(proposal.totalInclVat) })
          )}{approvals}.
        </p>
      ) : (
        <p>
          {t("The gateway could not build an order for this week{reason}. Nothing can be approved. See it in ", {
            reason: proposal.reasonCodes.length ? ` (${proposal.reasonCodes.join(", ")})` : "",
          })}{approvals}.
        </p>
      )}
      {proposal.uncountedCount > 0 ? (
        <p>
          {proposal.uncountedCount === 1
            ? t("{products} was never counted, so its full need is proposed.", { products: products(proposal.uncountedCount, t) })
            : t("{products} were never counted, so their full need is proposed.", { products: products(proposal.uncountedCount, t) })}
        </p>
      ) : null}
      {proposal.shortfallCount > 0 ? <p>{t("{products} cannot be fully covered.", { products: products(proposal.shortfallCount, t) })}</p> : null}
    </div>
  );
}

export function PlannerPage() {
  const t = useT();
  const api = useApi();
  const navigate = useNavigate();
  const search = useSearch({ from: "/planner" });
  const week = displayedWeek(search.week);
  const dates = useMemo(() => weekDates(week), [week]);
  const menu = useAsync(async () => Promise.all([api.getMenuPlan(week), api.listRecipes()]), [api, week]);
  const demand = useAsync(() => api.getDemand(dates[0], dates[6]), [api, week]);
  // Energy is extra: while it loads or when it fails, the plan shows without it.
  const nutrition = useAsync(() => api.getNutrition(dates[0], dates[6]), [api, week]);
  const [draft, setDraft] = useState<MenuPlanEntry[] | null>(null);
  const [dialog, setDialog] = useState<{ date: string; entry?: MenuPlanEntry } | null>(null);
  const [meal, setMeal] = useState("Lunch");
  const [recipeId, setRecipeId] = useState("");
  const [covers, setCovers] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [draftWeek, setDraftWeek] = useState(week);
  const [proposing, setProposing] = useState(false);
  const [outcome, setOutcome] = useState<ProposeOutcome | null>(null);

  useEffect(() => {
    if (menu.status === "ready") {
      setDraft(menu.data[0]);
      setDraftWeek(week);
    }
  }, [menu.status, menu.status === "ready" ? menu.data : null, week]);

  const saved = menu.status === "ready" && draftWeek === week ? menu.data[0] : [];
  const entries = draftWeek === week && draft !== null ? draft : saved;
  const recipes: Recipe[] = menu.status === "ready" ? menu.data[1] : [];
  const dirty = !sameEntries(entries, saved);

  async function changeWeek(next: string) {
    if (dirty && !window.confirm(t("Discard your unsaved changes and change week?"))) return;
    setDraft(null);
    setDraftWeek("");
    setError("");
    await navigate({ to: "/planner", search: { week: next } });
  }

  function openAdd(date: string) {
    setMeal("Lunch");
    setRecipeId(recipes[0]?.id ?? "");
    setCovers("");
    setError("");
    setDialog({ date });
  }

  function openEdit(entry: MenuPlanEntry) {
    setMeal(entry.meal);
    setRecipeId(entry.recipeId);
    setCovers(String(entry.covers));
    setError("");
    setDialog({ date: entry.date, entry });
  }

  function applyDialog() {
    const parsed = Number(covers);
    if (!meal.trim()) {
      setError(t("Enter a meal name."));
      return;
    }
    if (covers.trim() === "" || !Number.isInteger(parsed) || parsed < 0) {
      setError(t("Covers must be a whole number greater than or equal to zero."));
      return;
    }
    if (!recipeId) {
      setError(t("Choose a recipe."));
      return;
    }
    const entry: MenuPlanEntry = {
      id: dialog?.entry?.id ?? `draft-${randomHex()}`,
      date: dialog?.date ?? dates[0],
      meal: meal.trim(),
      recipeId,
      covers: parsed,
    };
    setDraft((current) => {
      const base = current ?? saved;
      return dialog?.entry ? base.map((item) => (item.id === entry.id ? entry : item)) : [...base, entry];
    });
    setDialog(null);
  }

  async function saveWeek() {
    setSaving(true);
    setError("");
    try {
      const menuDrafts: Draft<MenuPlanEntry>[] = entries.map(({ id, ...entry }) =>
        id.startsWith("draft-") ? entry : { ...entry, id },
      );
      await api.saveMenuPlan(week, menuDrafts);
      setDraft(null);
      // A proposal made from the plan before this save no longer describes the plan.
      setOutcome(null);
      menu.reload();
      demand.reload();
      nutrition.reload();
      toast.success(t("Week saved"));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      setSaving(false);
    }
  }

  // Delivery on the first day of the shown week that is today or later; none when the week has passed.
  const today = todayIso();
  const requestedDate = dates.find((date) => date >= today);
  const proposeBlocked = !requestedDate
    ? t("This week is in the past, so there is nothing to order for it.")
    : dirty
      ? t("Save the week first: the proposal uses the saved plan.")
      : "";

  /** Asks for a proposal only. Approving it is a person's step on the approvals page. */
  async function proposeOrder() {
    if (!requestedDate || proposing) return;
    setProposing(true);
    setOutcome(null);
    try {
      const proposal = await api.proposeOrderForPlan(dates[0], dates[6], requestedDate);
      setOutcome({ week, kind: "proposal", proposal });
    } catch (cause) {
      if (cause instanceof ApiError && cause.code === "NOTHING_NEEDED") setOutcome({ week, kind: "nothing" });
      else setOutcome({ week, kind: "error", message: cause instanceof Error ? cause.message : String(cause) });
    } finally {
      setProposing(false);
    }
  }

  function discard() {
    setDraft(saved);
    setError("");
  }

  return (
    <AppShell activeId="planner">
      <div className="mx-auto max-w-6xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("Menu plan")}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("Plan the week's menus and covers. The needs below come from this plan.")}
          </p>
        </header>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <Button variant="outline" onClick={() => void changeWeek(shiftWeek(week, -1))}>
            {t("Previous week")}
          </Button>
          <h2 className="text-lg font-semibold" aria-live="polite">
            {weekTitle(week, t)}
          </h2>
          <Button variant="outline" onClick={() => void changeWeek(shiftWeek(week, 1))}>
            {t("Next week")}
          </Button>
        </div>
        {menu.status === "loading" ? <LoadingState label={t("Loading menu plan")} /> : null}
        {menu.status === "error" ? <ErrorState message={menu.error.message} onRetry={menu.reload} /> : null}
        {menu.status === "ready" ? (
          <>
            {dirty ? (
              <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-muted/40 p-4">
                <p className="font-medium">{t("Unsaved changes")}</p>
                <div className="flex gap-2">
                  <Button variant="outline" onClick={discard}>
                    {t("Discard")}
                  </Button>
                  <Button onClick={() => void saveWeek()} disabled={saving}>
                    {saving ? t("Saving…") : t("Save week")}
                  </Button>
                </div>
              </div>
            ) : null}
            {error ? (
              <Alert variant="destructive" role="alert">
                <AlertDescription>{error}</AlertDescription>
              </Alert>
            ) : null}
            <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
              {dates.map((date) => {
                const dayEntries = entries.filter((entry) => entry.date === date);
                // The energy is of the saved plan: a day with unsaved changes shows none.
                const energy =
                  nutrition.status === "ready" && sameEntries(dayEntries, saved.filter((entry) => entry.date === date))
                    ? nutrition.data.days.find((day) => day.date === date)
                    : undefined;
                return (
                  <Card key={date}>
                    <CardHeader>
                      <CardTitle>
                        <h3>
                          {weekday(date)}{" "}
                          <span className="text-sm font-normal text-muted-foreground">{dateRange(date)}</span>
                        </h3>
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-3">
                      {dayEntries.length === 0 ? (
                        <p className="text-sm text-muted-foreground">{t("No menu entries")}</p>
                      ) : null}
                      {dayEntries.map((entry) => {
                        const recipe = recipes.find((item) => item.id === entry.recipeId);
                        return (
                          <div key={entry.id} className="space-y-2 rounded-md border p-3">
                            <div className="flex justify-between gap-2">
                              <div className="min-w-0">
                                <p className="font-medium">{entry.meal}</p>
                                <p className="text-sm tabular-nums text-muted-foreground">
                                  {recipe?.name ?? t("Recipe unavailable")} · {t("{count} covers", { count: formatNumber(entry.covers) })}
                                </p>
                              </div>
                              <div className="flex shrink-0 gap-1">
                                <Button variant="ghost" size="sm" onClick={() => openEdit(entry)}>
                                  {t("Edit")}
                                </Button>
                                <Button
                                  variant="ghost"
                                  size="sm"
                                  className="text-danger hover:text-danger"
                                  onClick={() =>
                                    setDraft((current) => (current ?? saved).filter((item) => item.id !== entry.id))
                                  }
                                >
                                  {t("Remove")}
                                </Button>
                              </div>
                            </div>
                          </div>
                        );
                      })}
                      {dayEntries.length > 0 && energy ? (
                        <p className="text-sm tabular-nums text-muted-foreground">
                          {energy.kcalPerCover == null
                            ? t("Energy per cover not known")
                            : t("about {kcal} kcal per cover", { kcal: formatNumber(energy.kcalPerCover) })}
                          {energy.kcalPerCover != null && !energy.complete ? ` · ${t("partly counted")}` : ""}
                        </p>
                      ) : null}
                      <Button className="w-full" variant="outline" onClick={() => openAdd(date)}>
                        {t("Add to {weekday}", { weekday: weekday(date) })}
                      </Button>
                    </CardContent>
                  </Card>
                );
              })}
            </div>
            {entries.length === 0 ? (
              <EmptyState title={t("No menu entries this week")}>{t("Add a meal to plan the kitchen’s needs.")}</EmptyState>
            ) : null}
            <section className="space-y-4" aria-labelledby="needs-heading">
              <div>
                <h2 id="needs-heading" className="text-xl font-semibold">
                  {t("What this week needs")}
                </h2>
                {dirty ? <p className="mt-1 text-sm text-muted-foreground">{t("This table shows the saved plan.")}</p> : null}
              </div>
              {nutrition.status === "ready" ? <EnergySummary nutrition={nutrition.data} /> : null}
              {nutrition.status === "error" ? (
                <p className="text-sm text-muted-foreground">{t("Energy numbers are not available right now.")}</p>
              ) : null}
              {demand.status === "loading" ? <LoadingState label={t("Loading weekly demand")} /> : null}
              {demand.status === "error" ? <ErrorState message={demand.error.message} onRetry={demand.reload} /> : null}
              {demand.status === "ready" ? <DemandList lines={demand.data} dates={dates} /> : null}
              <div className="space-y-2">
                <Button
                  className="w-full sm:w-auto"
                  onClick={() => void proposeOrder()}
                  disabled={proposing || proposeBlocked !== ""}
                  aria-describedby={proposeBlocked ? "propose-blocked" : undefined}
                >
                  {proposing ? t("Proposing…") : t("Propose order for this week")}
                </Button>
                {proposeBlocked ? (
                  <p id="propose-blocked" className="text-sm text-muted-foreground">
                    {proposeBlocked}
                  </p>
                ) : null}
                <div role="status" aria-live="polite" className="text-sm break-words">
                  {outcome && outcome.week === week ? <ProposeMessage outcome={outcome} /> : null}
                </div>
              </div>
              <div className="flex flex-wrap gap-4 text-sm">
                <Link to="/stock" className="font-medium text-primary underline underline-offset-4">
                  {t("Check stock")}
                </Link>
                <Link to="/requests" className="font-medium text-primary underline underline-offset-4">
                  {t("Ask the Buyer for an order")}
                </Link>
              </div>
            </section>
          </>
        ) : null}
      </div>
      <Dialog
        open={dialog !== null}
        onOpenChange={(open) => {
          if (!open) setDialog(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{dialog?.entry ? t("Edit menu entry") : t("Add menu entry")}</DialogTitle>
          </DialogHeader>
          <DialogBody className="space-y-4">
            <label className="grid gap-2 text-sm font-medium" htmlFor="planner-meal">
              {t("Meal")}
              <Input id="planner-meal" value={meal} onChange={(event) => setMeal(event.target.value)} />
            </label>
            <label className="grid gap-2 text-sm font-medium" htmlFor="planner-recipe">
              {t("Recipe")}
              <Select value={recipeId} onValueChange={setRecipeId}>
                <SelectTrigger id="planner-recipe" className="w-full">
                  <SelectValue placeholder={t("Choose a recipe")} />
                </SelectTrigger>
                <SelectContent>
                  {recipes.map((recipe) => (
                    <SelectItem key={recipe.id} value={recipe.id}>
                      {recipe.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
            <label className="grid gap-2 text-sm font-medium" htmlFor="planner-covers">
              {t("Covers")}
              <Input
                id="planner-covers"
                type="number"
                min="0"
                step="1"
                value={covers}
                onChange={(event) => setCovers(event.target.value)}
              />
            </label>
            {error ? (
              <p role="alert" className="text-sm text-destructive">
                {error}
              </p>
            ) : null}
          </DialogBody>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDialog(null)}>
              {t("Cancel")}
            </Button>
            <Button onClick={applyDialog}>{dialog?.entry ? t("Save entry") : t("Add entry")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </AppShell>
  );
}
