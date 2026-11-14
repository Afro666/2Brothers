import type { ReactNode } from "react";
import { useT } from "@/lib/i18n";

/** Nothing here yet: a blank, ruled page of the order pad with the words on a paper label. */
export function EmptyState({ title = "Nothing here yet", children }: { title?: string; children?: ReactNode }) {
  const t = useT();
  return (
    <div className="blank-slip px-5 py-7 text-center">
      <div className="inline-block max-w-full rounded-sm bg-card px-4 py-2">
        <h2 className="stamp text-[15px] leading-7">{t(title)}</h2>
        {children ? (
          <p className="text-sm leading-7 text-muted-foreground">
            {typeof children === "string" ? t(children) : children}
          </p>
        ) : null}
      </div>
    </div>
  );
}
