import { BookOpen, ChefHat, Inbox, Menu, Package, ScrollText, UserCheck, type LucideIcon } from "lucide-react";
import { type ReactNode, useState } from "react";

import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { cn } from "@/lib/utils";

export interface NavItem {
  id: string;
  label: string;
  href: string;
  icon: LucideIcon;
  /** A count shown beside the label, e.g. pending approvals. */
  count?: number;
}

export const NAV_ITEMS: NavItem[] = [
  { id: "requests", label: "Requests", href: "/requests", icon: Inbox },
  { id: "approvals", label: "Approvals", href: "/approvals", icon: UserCheck },
  { id: "orders", label: "Orders", href: "/orders", icon: Package },
  { id: "audit", label: "Audit log", href: "/audit", icon: ScrollText },
  { id: "catalog", label: "Catalog", href: "/catalog", icon: BookOpen },
];

function NavList({ items, activeId, onNavigate }: { items: NavItem[]; activeId?: string; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main">
      <ul className="space-y-1">
        {items.map((item) => {
          const active = item.id === activeId;
          const Icon = item.icon;
          return (
            <li key={item.id}>
              <a
                href={item.href}
                aria-current={active ? "page" : undefined}
                onClick={onNavigate}
                className={cn(
                  "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/50",
                  active ? "bg-accent text-accent-foreground" : "text-muted-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                <span className="flex-1">{item.label}</span>
                {item.count ? (
                  <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground tabular-nums">
                    {item.count}
                  </span>
                ) : null}
              </a>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function Brand() {
  return (
    <span className="flex items-center gap-2 font-semibold">
      <ChefHat className="size-5" aria-hidden />
      Kitchen Buyer
    </span>
  );
}

/**
 * The app frame: a fixed sidebar from `md` up; on a phone a top bar whose
 * menu button opens the same nav in a drawer.
 */
export function AppShell({
  items = NAV_ITEMS,
  activeId,
  children,
}: {
  items?: NavItem[];
  activeId?: string;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  return (
    <div className="min-h-screen bg-background md:flex">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col gap-6 border-r p-4 md:flex">
        <Brand />
        <NavList items={items} activeId={activeId} />
      </aside>

      <header className="sticky top-0 z-40 flex h-14 items-center gap-3 border-b bg-background/95 px-4 backdrop-blur md:hidden">
        <Button variant="ghost" size="icon" aria-label="Open menu" onClick={() => setOpen(true)}>
          <Menu />
        </Button>
        <Brand />
      </header>
      <Sheet open={open} onOpenChange={setOpen}>
        <SheetContent side="left">
          <SheetHeader>
            <SheetTitle>
              <Brand />
            </SheetTitle>
            <SheetDescription className="sr-only">Main navigation</SheetDescription>
          </SheetHeader>
          <NavList items={items} activeId={activeId} onNavigate={() => setOpen(false)} />
        </SheetContent>
      </Sheet>

      <main className="min-w-0 flex-1 px-4 py-6 md:px-8">{children}</main>
    </div>
  );
}
