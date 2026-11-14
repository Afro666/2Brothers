import { Link, type LinkProps } from "@tanstack/react-router";

import { NemotronMark } from "@/components/nemotron-mark";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useT } from "@/lib/i18n";

/**
 * The five jobs, in the order of one buying loop. `text` quotes the label a visitor looks for on
 * the page that `to` opens; `link` says where the link goes.
 */
export const NEMOTRON_JOBS = [
  {
    name: "Plan the menu",
    text: "A photo of next week's menu becomes a menu-plan proposal. Look for “Plan from a menu photo”.",
    link: "Open the menu plan",
    to: "/planner",
  },
  {
    name: "Buy the food",
    text: "A chef's sentence becomes an order proposal. Each card under “To approve” then has a “What Nemotron did” panel.",
    link: "Open Request an order",
    to: "/requests",
  },
  {
    name: "Sell a substitute",
    text: "Valio's selling agent offers a substitute before a shortage. While an offer is open, Home shows the “Offer from Valio Aimo” tile.",
    link: "See the offer on Home",
    to: "/",
  },
  {
    name: "Count the stock",
    text: "A shelf photo becomes stock counts that a person checks and saves. Look for “Count from a photo”.",
    link: "Open the stock count",
    to: "/stock",
  },
  {
    name: "Receive the delivery",
    text: "A photo of the delivery note is read, and plain code compares it with the order and works out the euros to claim. Open a placed order and look for “Photo of the delivery note”.",
    link: "Open the order history",
    to: "/orders",
  },
];

/** Smaller jobs of the same model. Each one has a route and a place on that page. */
export const NEMOTRON_ALSO = [
  {
    text: "Several products in one sentence: Nemotron splits the text into needs, and rules match the products.",
    link: "Open Request an order",
    to: "/requests",
  },
  {
    text: "A photo of a package label: the allergens are compared with the catalog (“Photo of the label” on a placed order).",
    link: "Open the order history",
    to: "/orders",
  },
  {
    text: "A photo of a supplier's price list becomes product rows to check (“Add from a photo of the price list”).",
    link: "Open the suppliers",
    to: "/suppliers",
  },
  {
    text: "A buying note for Valio's planner, with every number checked by code (“Buying note”).",
    link: "Open the demand page",
    to: "/demand",
  },
];

/** At least 40 px high, so a thumb hits it; the underline keeps it a link, not a button. */
const LINK = "inline-flex min-h-10 items-center font-medium text-primary underline underline-offset-4";

/**
 * "Nemotron at work" on the About page: where the model works on this site, one row per job and
 * a link straight to the place. Static text; the numbers are in the usage card below it.
 */
export function NemotronJobsCard() {
  const t = useT();
  return (
    <Card>
      <CardHeader>
        <CardTitle>
          <h2 id="about-nemotron-jobs">
            {t("Nemotron at work")}
            <NemotronMark side="after" />
          </h2>
        </CardTitle>
        <p className="max-w-prose text-sm text-muted-foreground">
          {t("One model, five jobs, one buying loop. It never sets a quantity or a price: the engine does, and a person approves.")}
        </p>
      </CardHeader>
      <CardContent className="space-y-4 text-sm">
        <ol aria-label={t("The five jobs")} className="divide-y border-y">
          {NEMOTRON_JOBS.map((job, index) => (
            <li key={job.name} className="flex gap-3 py-3">
              <span
                aria-hidden
                className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-sm text-primary-foreground tabular-nums"
              >
                {index + 1}
              </span>
              <div className="min-w-0 flex-1 sm:grid sm:grid-cols-[1fr_auto] sm:items-start sm:gap-x-4">
                <div className="space-y-1">
                  <h3 className="pt-0.5 font-semibold">{t(job.name)}</h3>
                  <p className="break-words text-muted-foreground">{t(job.text)}</p>
                </div>
                <Link to={job.to as LinkProps["to"]} className={`${LINK} sm:justify-end sm:text-right`}>
                  {t(job.link)}
                </Link>
              </div>
            </li>
          ))}
        </ol>
        <div className="space-y-1">
          <h3 id="about-nemotron-also" className="font-medium">
            {t("Also")}
          </h3>
          <ul aria-labelledby="about-nemotron-also" className="space-y-2 sm:space-y-0">
            {NEMOTRON_ALSO.map((row) => (
              <li key={row.text} className="sm:flex sm:items-baseline sm:justify-between sm:gap-x-4">
                <p className="break-words text-muted-foreground">{t(row.text)}</p>
                <Link to={row.to as LinkProps["to"]} className={`${LINK} sm:shrink-0`}>
                  {t(row.link)}
                </Link>
              </li>
            ))}
          </ul>
        </div>
        <div className="sm:flex sm:items-baseline sm:gap-x-2">
          <p className="text-muted-foreground">{t("How much the model worked is counted in the next card.")}</p>
          <a href="#about-model" className={`${LINK} sm:shrink-0`}>
            {t("See the usage numbers")}
          </a>
        </div>
      </CardContent>
    </Card>
  );
}
