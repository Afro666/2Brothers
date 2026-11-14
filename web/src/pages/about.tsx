import { Link } from "@tanstack/react-router";

import { AppShell } from "@/components/purchasing/app-shell";
import { ModelUsageCard } from "@/components/purchasing/model-usage-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

const STEPS = [
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

const RULES = [
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

/** One page for a first-time visitor: what this is, how an order moves, and the rules it keeps. */
export function AboutPage() {
  return (
    <AppShell activeId="about">
      <div className="mx-auto max-w-3xl space-y-8">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">About Kitchen Buyer</h1>
          <p className="max-w-prose text-muted-foreground">
            A purchasing agent that Valio Aimo gives to its kitchen customers. It works out what a kitchen needs and
            proposes the order. A person approves it.
          </p>
        </header>

        <section aria-labelledby="about-problem" className="space-y-2">
          <h2 id="about-problem" className="text-lg font-semibold">
            The problem
          </h2>
          <p className="max-w-prose text-sm">
            A professional kitchen orders food several times a week. Someone counts the stock, reads the menu, works out
            the quantities and sends the order before the supplier’s cut-off. It takes time, and a wrong number means
            waste or a missing ingredient.
          </p>
          <p className="max-w-prose text-sm">
            The wholesaler sees the demand only when the orders arrive. That is too late to prevent a shortage.
          </p>
        </section>

        <section aria-labelledby="about-flow" className="space-y-3">
          <h2 id="about-flow" className="text-lg font-semibold">
            How an order moves
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
                      <h3>{step.title}</h3>
                    </CardTitle>
                  </CardHeader>
                  <CardContent className="text-sm text-muted-foreground">{step.text}</CardContent>
                </Card>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="about-model">
          <ModelUsageCard />
        </section>

        <section aria-labelledby="about-sides" className="space-y-3">
          <h2 id="about-sides" className="text-lg font-semibold">
            Two sides
          </h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <Card>
              <CardHeader>
                <CardTitle>
                  <h3>The kitchen</h3>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                Asks for products, approves orders, counts stock and plans the menu for the week. Valio Aimo is one
                supplier; the kitchen can add its own suppliers and products.
              </CardContent>
            </Card>
            <Card>
              <CardHeader>
                <CardTitle>
                  <h3>Valio</h3>
                </CardTitle>
              </CardHeader>
              <CardContent className="text-sm text-muted-foreground">
                Sees what the kitchens that share their forecast expect to need, per product and day, against what is
                available. A shortage shows before the orders arrive.
              </CardContent>
            </Card>
          </div>
          <p className="text-sm text-muted-foreground">Switch sides with “Your role” in the menu.</p>
        </section>

        <section aria-labelledby="about-rules" className="space-y-3">
          <h2 id="about-rules" className="text-lg font-semibold">
            Trust rules
          </h2>
          <ul className="space-y-3">
            {RULES.map((rule) => (
              <li key={rule.title} className="rounded-lg border px-4 py-3">
                <h3 className="font-medium">{rule.title}</h3>
                <p className="mt-1 text-sm text-muted-foreground">{rule.text}</p>
              </li>
            ))}
          </ul>
          <p className="text-sm">
            <Link to="/audit" className="font-medium text-primary underline underline-offset-4">
              Open the activity log
            </Link>
          </p>
          <p className="text-sm">
            <a href="/api/docs" className="font-medium text-primary underline underline-offset-4">
              API docs (OpenAPI)
            </a>
            {" · "}
            <a
              href="https://github.com/Afro666/2Brothers/blob/main/docs/choices.md"
              className="font-medium text-primary underline underline-offset-4"
            >
              Why it is built this way
            </a>
          </p>
        </section>
      </div>
    </AppShell>
  );
}
