import type { ReactNode } from "react";
import { Link } from "@tanstack/react-router";

import { EmptyState } from "@/components/purchasing/empty-state";
import { ErrorState } from "@/components/purchasing/error-state";
import { LoadingState } from "@/components/purchasing/loading-state";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export function Tile({
  title,
  children,
  href,
  linkLabel,
}: {
  title: string;
  children: ReactNode;
  href: string;
  linkLabel: string;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {children}
        <Link to={href} className="text-sm font-medium text-primary underline underline-offset-4">
          {linkLabel}
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
  if (status === "loading") return <LoadingState label="Loading dashboard tile" />;
  if (status === "error")
    return <ErrorState message={error?.message ?? "Could not load this tile."} onRetry={reload} />;
  if (empty || data === null) return <EmptyState title="No data yet" />;
  return children(data);
}
