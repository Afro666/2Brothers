import type { ReactNode } from "react";

export function EmptyState({ title = "Nothing here yet", children }: { title?: string; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed px-5 py-8 text-center">
      <h2 className="font-medium">{title}</h2>
      {children ? <p className="mt-1 text-sm text-muted-foreground">{children}</p> : null}
    </div>
  );
}
