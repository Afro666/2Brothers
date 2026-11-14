import { Link, type LinkProps } from "@tanstack/react-router";

import { AppShell } from "@/components/purchasing/app-shell";
import { AtlasCard } from "@/components/purchasing/atlas-card";
import { ModelUsageCard } from "@/components/purchasing/model-usage-card";
import { NemotronJobsCard } from "@/components/purchasing/nemotron-jobs-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { useT } from "@/lib/i18n";

export const STEPS = [
  {
    title: "Request",
    text: "The chef says what the kitchen needs, for example “1,000 L of lactose-free milk by Monday”. The planner also works out the need from the menu, the covers and the stock.",
  },
  {
    title: "Lookup",
    text: "The Buyer agent searches the Valio Aimo catalog and asks for the price, the stock and the delivery date of each product. If the first choice cannot arrive in time, it proposes a substitute and says what changes.",
  },
  {
    title: "Order at a fixed price",
    text: "The gateway works out the exact total before anyone decides. The order can be placed only at that total: if the price or the stock has moved, the order is refused, not sent.",
  },
  {
    title: "Approval",
    text: "A person reads the order, the total and what to check, then approves or rejects it. The agent cannot approve its own order.",
  },
];

export const RULES = [
  {
    title: "A person approves every order",
    text: "The agent proposes. It never approves, however small the order is.",
  },
  {
    title: "Unknown is never treated as zero or safe",
    text: "Stock that was not measured, a missing price or missing allergen data is shown as “unknown”, and a person has to check it.",
  },
  {
    title: "Everything is audited",
    text: "Every step is in the audit log: who did it, what, when and why.",
  },
  {
    title: "Forecasts are shared only with consent",
    text: "The kitchen chooses which suppliers see its forecast and can turn sharing off. Only the forecast is shared, never menus or prices from other suppliers.",
  },
];

const BUILT_WITH = [
  {
    company: "MongoDB Atlas",
    logo: "mongodb.svg",
    label: "Best Use of MongoDB Atlas",
    title: "MongoDB Atlas: the only database",
    rows: [
      {
        text: "Product search in English, Finnish and Swedish, one typo allowed, allergens excluded (Atlas Search)",
        link: "Search the catalog",
        to: "/catalog",
      },
      {
        text: "New proposals reach the inbox without a refresh (change streams)",
        link: "Open the inbox",
        to: "/approvals",
      },
      {
        text: "Portion creep in a standing order, this week against the weeks before (time-series collections and a $setWindowFields aggregation)",
        link: "See it on Home",
        to: "/",
      },
      {
        text: "Every order stored once, money that never rounds, and a log nobody can change unnoticed (unique index, Decimal128, hash-chained audit log)",
        link: "Run the tamper check",
        to: "/trust",
      },
      {
        // The counts are live in the Atlas card further down: no number is repeated here.
        text: "Search by meaning, joined with the text search by $rankFusion (Atlas Vector Search)",
        link: "See the live Atlas numbers",
        href: "#about-atlas",
      },
    ],
  },
  {
    company: "NVIDIA Nemotron 3.5 Super VL",
    logo: "nvidia.svg",
    label: "Best Use of Nemotron",
    title: "NVIDIA Nemotron 3.5 Super VL: the Buyer agent",
    rows: [
      {
        text: "Reads the chef's sentence and picks the products. Code calls the tools. It never sets a quantity or a price and it has no approve tool.",
        link: "Request an order",
        to: "/requests",
      },
      {
        text: "Reads photos: a shelf into stock counts, a delivery note against its order, a menu into a week plan",
        link: "Count from a photo",
        to: "/stock",
      },
      {
        text: "Works for the supplier too: Valio's selling agent picks a substitute before a shortage",
        link: "The offer on Home",
        to: "/",
      },
      {
        text: "Writes for people too: a short reason on a proposal and a buying note for Valio's planner. Code checks every number in them before they are shown.",
        link: "See a proposal",
        to: "/approvals",
      },
    ],
  },
];

/** Named, with one line each: the work goes to the two above (#1388). */
const ALSO_USED = [
  {
    company: "Context.dev",
    logo: "contextdev.png",
    text: "Context.dev reads the Finnish Food Authority's recall list and matches it to this kitchen.",
    link: "See the recall box",
    to: "/approvals",
  },
  { company: "OpenAI Codex", logo: "openai.svg", text: "OpenAI Codex wrote part of the Buyer agent and its tools." },
  { company: "Verda", logo: "verda.svg", text: "Verda runs the model's endpoint and this site." },
];

/** One page for a first-time visitor: what this is, how an order moves, and the rules it keeps. */
export function AboutPage() {
  const t = useT();
  return (
    <AppShell activeId="about">
      <div className="mx-auto max-w-3xl space-y-8">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{t("About Kitchen Buyer")}</h1>
          <p className="max-w-prose text-muted-foreground">
            {t("A purchasing agent that Valio Aimo gives to its kitchen customers. It works out what a kitchen needs and proposes the order. A person approves it.")}
          </p>
        </header>

        <section aria-labelledby="about-built-with" className="space-y-3">
          <h2 id="about-built-with" className="text-lg font-semibold">
            {t("Built with")}
          </h2>
          <p className="max-w-prose text-sm text-muted-foreground">
            {t("MongoDB Atlas holds every record and NVIDIA Nemotron is the Buyer agent. Each card says what the service does and where you can see it.")}
          </p>
          <div className="grid gap-3 md:grid-cols-2">
            {BUILT_WITH.map((service) => (
              <Card key={service.company} className="h-full">
                <CardHeader>
                  <div className="flex items-start gap-3">
                    <div className="flex size-14 shrink-0 items-center justify-center rounded-md border bg-white p-2">
                      <img
                        src={`${import.meta.env.BASE_URL}logos/${service.logo}`}
                        alt={t("{company} logo", { company: service.company })}
                        loading="lazy"
                        width={40}
                        height={40}
                        className="size-10 object-contain"
                      />
                    </div>
                    <div className="space-y-1">
                      <p className="text-xs text-muted-foreground">{t(service.label)}</p>
                      <CardTitle>
                        <h3 className="leading-snug">{t(service.title)}</h3>
                      </CardTitle>
                    </div>
                  </div>
                </CardHeader>
                <CardContent>
                  <ul className="space-y-3 text-sm">
                    {service.rows.map((row) => (
                      <li key={row.text}>
                        <p className="text-muted-foreground">{t(row.text)}</p>
                        {"to" in row && row.link && (
                          <Link
                            to={row.to as LinkProps["to"]}
                            className="font-medium text-primary underline underline-offset-4"
                          >
                            {t(row.link)}
                          </Link>
                        )}
                        {"href" in row && (
                          <a href={row.href} className="font-medium text-primary underline underline-offset-4">
                            {t(row.link)}
                          </a>
                        )}
                      </li>
                    ))}
                  </ul>
                </CardContent>
              </Card>
            ))}
          </div>
          <ul className="grid gap-3 text-sm sm:grid-cols-3" aria-label={t("Also used")}>
            {ALSO_USED.map((service) => (
              <li key={service.company} className="flex items-start gap-3 rounded-md border p-3">
                <span className="flex size-10 shrink-0 items-center justify-center rounded-md border bg-white p-1.5">
                  <img
                    src={`${import.meta.env.BASE_URL}logos/${service.logo}`}
                    alt={t("{company} logo", { company: service.company })}
                    loading="lazy"
                    width={28}
                    height={28}
                    className="size-7 object-contain"
                  />
                </span>
                <span className="min-w-0">
                  <span className="text-muted-foreground">{t(service.text)}</span>{" "}
                  {service.to ? (
                    <Link to={service.to as LinkProps["to"]} className="font-medium text-primary underline underline-offset-4">
                      {t(service.link)}
                    </Link>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
          <p className="text-sm text-muted-foreground">
            {t("Three people built it with coding agents. Every change is one issue, one branch and one pull request with an automatic review.")}
          </p>
        </section>

        <section aria-labelledby="about-problem" className="space-y-2">
          <h2 id="about-problem" className="text-lg font-semibold">
            {t("The problem")}
          </h2>
          <p className="max-w-prose text-sm">
            {t("A professional kitchen orders food several times a week. Someone counts the stock, reads the menu, works out the quantities and sends the order before the supplier’s cut-off. It takes time, and a wrong number means waste or a missing ingredient.")}
          </p>
          <p className="max-w-prose text-sm">
            {t("The wholesaler sees the demand only when the orders arrive. That is too late to prevent a shortage.")}
          </p>
        </section>

        <section aria-labelledby="about-flow" className="space-y-3">
          <h2 id="about-flow" className="text-lg font-semibold">
            {t("How an order moves")}
          </h2>
          <ol className="grid gap-3 sm:grid-cols-2">
            {STEPS.map((step, index) => (
              <li key={step.title}>
                <Card className="h-full">
                  <CardHeader>
                    <CardTitle className="flex items-center gap-2">
                      <span
                        aria-hidden
                        className="flex size-7 shrink-0 items-center justify-center rounded-full bg-primary text-sm text-primary-foreground tabular-nums"
                      >
                        {index + 1}
                      </span>
                      <h3>{t(step.title)}</h3>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm text-muted-foreground">{t(step.text)}</CardContent>
                </Card>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="about-nemotron-jobs">
          <NemotronJobsCard />
        </section>

        <section aria-labelledby="about-model">
          <ModelUsageCard />
        </section>

        <section aria-labelledby="about-atlas">
          <AtlasCard />
        </section>

        <section aria-labelledby="about-sides" className="space-y-3">
          <h2 id="about-sides" className="text-lg font-semibold">
            {t("Two sides")}
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>
                  <h3>{t("The kitchen")}</h3>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                {t("Asks for products, approves orders, counts stock and plans the menu for the week. Valio Aimo is one supplier; the kitchen can add its own suppliers and products.")}
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>
                  <h3>Valio</h3>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                {t("Sees what the kitchens that share their forecast expect to need, per product and day, against what is available. A shortage shows before the orders arrive.")}
              </CardContent>
            </Card>
          </div>
          <p className="text-sm text-muted-foreground">{t("Switch sides with “Your role” in the menu.")}</p>
        </section>

        <section aria-labelledby="about-rules" className="space-y-3">
          <h2 id="about-rules" className="text-lg font-semibold">
            {t("Trust rules")}
          </h2>
          <ul className="space-y-3">
            {RULES.map((rule) => (
              <li key={rule.title} className="rounded-lg border px-4 py-3">
                <h3 className="font-medium">{t(rule.title)}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{t(rule.text)}</p>
              </li>
            ))}
          </ul>
          <p className="text-sm">
            <Link to="/audit" className="font-medium text-primary underline underline-offset-4">
              {t("Open the activity log")}
            </Link>
          </p>
          <p className="text-sm">
            <a href="/api/docs" className="font-medium text-primary underline underline-offset-4">
              {t("API docs (OpenAPI)")}
            </a>
            {" · "}
            <a
              href="https://github.com/Afro666/2Brothers/blob/main/docs/choices.md"
              className="font-medium text-primary underline underline-offset-4"
            >
              {t("Why it is built this way")}
            </a>
          </p>
        </section>
      </div>
    </AppShell>
  );
}
