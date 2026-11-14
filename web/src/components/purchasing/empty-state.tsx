import type { ReactNode } from "react";
import { useT } from "@/lib/i18n";

export function EmptyState({ title = "Nothing here yet", children }: { title?: string; children?: ReactNode }) {
  const t = useT();
  return (
    <div className="rounded-lg border border-dashed px-5 py-8 text-center">
      <h2 className="font-medium">{t(title)}</h2>
      {children ? (
        <p className="mt-1 text-sm text-muted-foreground">{typeof children === "string" ? t(children) : children}</p>
      ) : null}
    </div>
  );
}
