import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";

import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import { useT } from "@/lib/i18n";

export function Tile({
  title,
  children,
  href,
  linkLabel,
  emphasis = false,
}: {
  title: string;
  children: ReactNode;
  href: string;
  linkLabel: string;
  emphasis?: boolean;
}) {
  return (
    <Card className={emphasis ? "docket" : undefined}>
      <CardHeader>
        <CardTitle className="label-caps leading-4">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {children}
        <Link
          to={href}
          className={
            emphasis
              ? buttonVariants({ className: "w-full sm:w-auto" })
              : "inline-flex items-center gap-1 text-sm font-medium text-foreground underline decoration-border underline-offset-4 hover:decoration-foreground"
          }
        >
          {linkLabel}
          <ArrowRight aria-hidden />
        </Link>
      </CardContent>
    </Card>
  );
}

export function TileState<T>({
  status,
  error,
  reload,
  data,
  empty,
  children,
}: {
  status: "loading" | "error" | "ready";
  error: Error | null;
  reload: () => void;
  data: T | null;
  empty: boolean;
  children: (value: T) => ReactNode;
}) {
  const t = useT();
  if (status === "loading") return <LoadingState label={t("Loading dashboard tile")} />;
  if (status === "error")
    return <ErrorState message={error?.message ?? t("Could not load this tile.")} onRetry={reload} />;
  if (empty || data === null) return <EmptyState title={t("No data yet")} />;
  return children(data);
}
