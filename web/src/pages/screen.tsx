import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";

export function ScreenPage({ title, description, activeId }: { title: string; description: string; activeId: string }) {
  return (
    <AppShell activeId={activeId}>
      <div className="mx-auto max-w-5xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{title}</h1>
          <p className="max-w-prose text-sm text-muted-foreground">{description}</p>
        </header>
        <EmptyState title="Nothing here yet">This screen is not built yet.</EmptyState>
      </div>
    </AppShell>
  );
}
