import { Link } from "@tanstack/react-router";
import { Camera } from "lucide-react";
import { useRef, useState } from "react";

import { useApi } from "@/api";
import type { AuditActor, MenuPhotoDish, MenuPhotoRead } from "@/api/types";
import { ApiError } from "@/api/types";
import { Button } from "@/components/ui/button";
import { formatDate, formatNumber } from "@/lib/format";
import { getLanguage, useT } from "@/lib/i18n";
import { downscalePhoto } from "@/lib/shelf-photo";
import { NemotronMark } from "@/components/nemotron-mark";

/** The name people know; the gateway's `model` field is the id (`nemotron-3.5-super-vl`). */
const MODEL_NAME = "Nemotron 3.5 Super VL";

type Translate = ReturnType<typeof useT>;

function weekday(date: string): string {
  return new Intl.DateTimeFormat(getLanguage() === "fi" ? "fi-FI" : "en-GB", { weekday: "long", timeZone: "UTC" }).format(
    new Date(`${date}T12:00:00Z`),
  );
}

/** The gateway's error codes in plain words (docs/contract.md, "Plan from a menu photo"). */
function errorText(problem: unknown, t: Translate): string {
  const code = problem instanceof ApiError ? problem.code : "";
  const status = problem instanceof ApiError ? problem.status : undefined;
  if (code === "VISION_NOT_CONFIGURED" || code === "VISION_UNAVAILABLE" || code === "VISION_TIMEOUT") {
    return t("The model is not answering right now. Plan the week by hand or try again later.");
  }
  if (code === "VISION_REPLY_INVALID") return t("The model's answer could not be used. Try again, or plan the week by hand.");
  if (code === "IMAGE_TOO_LARGE") return t("The photo is too large. Take it again from a little further away.");
  if (code === "NOT_AN_IMAGE") return t("This file is not a photo. Choose a JPEG or PNG photo.");
  if (code === "NOTHING_MATCHED") return t("No dish on the photo matches one of your recipes. Add the recipes first, or plan the week by hand.");
  if (code === "MENU_PHOTO_BUSY") return t("Another menu photo is being read. Wait for it, then try again.");
  if (code === "NOT_FOUND" || status === 404) {
    return t("Reading a menu photo is not switched on on this server yet. Plan the week by hand.");
  }
  const message = problem instanceof Error ? problem.message : String(problem);
  return t("The photo was not read: {error} Plan the week by hand or try again.", { error: message });
}

function DishLine({ dish }: { dish: MenuPhotoDish }) {
  const t = useT();
  const known = dish.status === "MATCHED";
  return (
    <li className="space-y-0.5 py-2 text-sm" data-testid="menu-photo-dish">
      <p className="break-words">
        <span className="font-medium">“{dish.dish}”</span>
        {dish.covers != null ? (
          <span className="tabular-nums text-muted-foreground"> · {t("{count} covers", { count: formatNumber(dish.covers) })}</span>
        ) : null}
      </p>
      {known ? (
        <p className="break-words text-muted-foreground">
          {t("Matched to recipe {recipe}.", { recipe: dish.recipeName ?? dish.recipeId ?? "" })}{" "}
          {dish.inProposal ? null : t("Not in the proposal: the menu shows no day or no covers for it.")}
        </p>
      ) : (
        <p className="break-words font-medium text-warning">
          {t("Not known: add it to your")}{" "}
          <Link to="/products" className="text-primary underline underline-offset-4">
            {t("recipes")}
          </Link>
          {t(", or plan this day by hand.")}
        </p>
      )}
    </li>
  );
}

/** The dishes per day, in date order; dishes without a day last. */
function DishList({ dishes }: { dishes: MenuPhotoDish[] }) {
  const t = useT();
  const days = [...new Set(dishes.map((dish) => dish.day))].sort((left, right) =>
    left === null ? 1 : right === null ? -1 : left.localeCompare(right),
  );
  return (
    <div className="space-y-3" aria-label={t("Dishes read from the menu")} role="group">
      {days.map((day) => (
        <div key={day ?? "none"}>
          <h3 className="text-sm font-semibold">
            {day ? (
              <>
                {weekday(day)} <span className="font-normal text-muted-foreground">{formatDate(day)}</span>
              </>
            ) : (
              t("No day on the menu")
            )}
          </h3>
          <ul className="divide-y">
            {dishes
              .filter((dish) => dish.day === day)
              .map((dish, index) => (
                <DishLine key={`${index}-${dish.dish}`} dish={dish} />
              ))}
          </ul>
        </div>
      ))}
    </div>
  );
}

function Outcome({ read }: { read: MenuPhotoRead }) {
  const t = useT();
  const matched = read.dishes.filter((dish) => dish.status === "MATCHED").length;
  const unknown = read.dishes.length - matched;
  return (
    <div className="space-y-1 text-sm">
      <p>
        <NemotronMark />
        {read.durationMs == null
          ? t("{model} read {count} dishes: {matched} matched to your recipes, {unknown} not known.", {
              model: MODEL_NAME,
              count: read.dishes.length,
              matched,
              unknown,
            })
          : t("{model} read {count} dishes in {seconds} s: {matched} matched to your recipes, {unknown} not known.", {
              model: MODEL_NAME,
              count: read.dishes.length,
              seconds: (read.durationMs / 1000).toFixed(1),
              matched,
              unknown,
            })}
      </p>
      {read.proposal ? (
        <p>
          {t("A proposal for the matched dishes waits in ")}
          <Link to="/approvals" className="font-medium text-primary underline underline-offset-4">
            {t("Orders > To approve")}
          </Link>
          {t(". A person approves it there. Nothing is ordered from this page.")}
        </p>
      ) : read.noProposalReason === "NOTHING_NEEDED" ? (
        <p>{t("Stock covers the matched dishes. No proposal was made, and nothing is ordered.")}</p>
      ) : (
        <p>{t("No proposal was made: no matched dish has a day and covers. Plan the week by hand.")}</p>
      )}
    </div>
  );
}

/**
 * "Plan from a menu photo" on the Planner page (#1136). The person takes or picks a photo of
 * next week's menu; the browser scales it down; the gateway has Nemotron 3.5 Super VL read the
 * dishes, matches them to recipes, and makes a proposal that waits for a person in the inbox.
 * This panel orders nothing and changes no saved plan.
 */
export function MenuPhotoPlan({
  from,
  to,
  requestedDate,
  actor,
  disabled,
}: {
  from: string;
  to: string;
  requestedDate?: string;
  actor: AuditActor;
  disabled?: boolean;
}) {
  const t = useT();
  const api = useApi();
  const camera = useRef<HTMLInputElement>(null);
  const picker = useRef<HTMLInputElement>(null);
  const latest = useRef(0);
  const [reading, setReading] = useState(false);
  const [error, setError] = useState<{ text: string; dishes: MenuPhotoDish[] } | null>(null);
  const [read, setRead] = useState<MenuPhotoRead | null>(null);
  // A read belongs to the week it was asked for.
  const shown = read && read.from === from && read.to === to ? read : null;

  async function readPhoto(file: File | undefined) {
    if (!file || reading) return;
    const turn = ++latest.current;
    setReading(true);
    setError(null);
    setRead(null);
    try {
      const answer = await api.readMenuPhoto(await downscalePhoto(file), { from, to, requestedDate }, actor);
      if (turn === latest.current) setRead(answer);
    } catch (problem) {
      if (turn !== latest.current) return;
      const dishes =
        problem instanceof ApiError && Array.isArray(problem.details.dishes) ? (problem.details.dishes as MenuPhotoDish[]) : [];
      setError({ text: errorText(problem, t), dishes });
    } finally {
      if (turn === latest.current) setReading(false);
    }
  }

  const input = (ref: React.RefObject<HTMLInputElement | null>, label: string, capture: boolean) => (
    <input
      ref={ref}
      type="file"
      accept="image/*"
      // On a phone this opens the back camera; a laptop shows the file dialog.
      capture={capture ? "environment" : undefined}
      className="sr-only"
      tabIndex={-1}
      aria-label={label}
      onChange={(event) => {
        const file = event.currentTarget.files?.[0];
        event.currentTarget.value = ""; // the same photo can be chosen again
        void readPhoto(file);
      }}
    />
  );

  return (
    <section aria-labelledby="menu-photo-title" className="space-y-3 rounded-lg border bg-card p-4">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="space-y-1">
          <h2 id="menu-photo-title" className="text-base font-semibold">
            {t("Plan from a menu photo")}
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">
            <NemotronMark />
            {t("{model} reads a photo of this week's menu and matches each dish to your recipes. A proposal waits in the inbox; nothing is ordered here.", {
              model: MODEL_NAME,
            })}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap gap-2">
          <Button type="button" disabled={disabled || reading} onClick={() => camera.current?.click()}>
            <Camera aria-hidden />
            {t("Take a photo")}
          </Button>
          <Button type="button" variant="outline" disabled={disabled || reading} onClick={() => picker.current?.click()}>
            {t("Choose a file")}
          </Button>
        </div>
        {input(camera, t("Take a photo of the menu"), true)}
        {input(picker, t("Choose a photo of the menu"), false)}
      </div>
      <div role="status" aria-live="polite">
        {reading ? (
          <p className="text-sm"><NemotronMark />{t("{model} is reading the menu. This takes a few seconds.", { model: MODEL_NAME })}</p>
        ) : null}
        {!reading && shown ? <Outcome read={shown} /> : null}
      </div>
      {error ? (
        <p role="alert" className="rounded-md border border-destructive/40 px-3 py-2 text-sm text-destructive">
          {error.text}
        </p>
      ) : null}
      {error && error.dishes.length > 0 ? <DishList dishes={error.dishes} /> : null}
      {shown && shown.dishes.length > 0 ? <DishList dishes={shown.dishes} /> : null}
    </section>
  );
}
