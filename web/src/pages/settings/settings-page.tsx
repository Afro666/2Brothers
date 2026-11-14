import { Link, useParams } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";

import { AppShell } from "@/components/purchasing/app-shell";
import { EmptyState } from "@/components/purchasing/empty-state";
import { cn } from "@/lib/utils";
import { SETTINGS_SECTIONS } from "@/pages/settings/sections";

const FOCUS = "outline-none focus-visible:ring-[3px] focus-visible:ring-ring/70";

/**
 * The settings area. From `md` up: the section list on the left, the chosen
 * section beside it. On a phone: `/settings` is the list alone and a section
 * is a page of its own with a link back.
 */
export function SettingsPage() {
  const { section: sectionId } = useParams({ strict: false });
  const Section = SETTINGS_SECTIONS.find((section) => section.id === sectionId)?.component;
  return (
    <AppShell activeId="settings">
      <div className="mx-auto max-w-5xl space-y-6">
        <h1 className="text-2xl font-semibold">Settings</h1>
        <div className="md:grid md:grid-cols-[13rem_minmax(0,1fr)] md:gap-8">
          <nav aria-label="Settings sections" className={cn(sectionId && "hidden md:block")}>
            <ul className="space-y-1">
              {SETTINGS_SECTIONS.map((section) => {
                const active = section.id === sectionId;
                return (
                  <li key={section.id}>
                    <Link
                      to="/settings/$section"
                      params={{ section: section.id }}
                      aria-current={active ? "page" : undefined}
                      className={cn(
                        "block rounded-md px-3 py-2 text-sm font-medium hover:bg-accent",
                        FOCUS,
                        active ? "bg-accent text-accent-foreground" : "text-muted-foreground",
                      )}
                    >
                      {section.label}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </nav>
          <div className={cn("min-w-0 space-y-4", !sectionId && "hidden md:block")}>
            {sectionId ? (
              <Link
                to="/settings"
                className={cn(
                  "inline-flex items-center gap-1 rounded-md text-sm text-muted-foreground md:hidden",
                  FOCUS,
                )}
              >
                <ChevronLeft className="size-4" aria-hidden />
                All settings
              </Link>
            ) : null}
            {Section ? (
              <Section />
            ) : (
              <EmptyState title={sectionId ? "No such settings section" : "Choose a section"}>
                Pick a section from the list.
              </EmptyState>
            )}
          </div>
        </div>
      </div>
    </AppShell>
  );
}
