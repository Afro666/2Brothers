import type { ReactNode } from "react";

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
  return (
    <section className="space-y-5">
      <header className="space-y-1">
        <h2 className="text-lg font-semibold">{title}</h2>
        <p className="max-w-prose text-sm text-muted-foreground">{description}</p>
      </header>
      {children}
    </section>
  );
}
