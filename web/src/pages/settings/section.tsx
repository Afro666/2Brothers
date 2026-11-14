import type { ReactNode } from "react";

import { useT } from "@/lib/i18n";

/** The frame every settings section uses: its heading, one line on what it is for, then its content. */
export function SettingsSection({
  title,
  description,
  children,
}: {
  title: string;
  description: string;
  children?: ReactNode;
}) {
  const t = useT();
  return (
    <section className="space-y-5">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">{t(title)}</h2>
        <p className="max-w-prose text-sm text-muted-foreground">{t(description)}</p>
      </header>
      {children}
    </section>
  );
}
