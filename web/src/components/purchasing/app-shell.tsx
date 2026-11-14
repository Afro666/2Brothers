import { Link, type LinkProps, useRouterState } from "@tanstack/react-router";
import {
  Archive,
  BookOpen,
  CalendarDays,
  ChefHat,
  House,
  Inbox,
  Info,
  Menu,
  Package,
  ScrollText,
  Settings,
  ShoppingBasket,
  TrendingUp,
  Truck,
  UserCheck,
  type LucideIcon,
} from "lucide-react";
import { type ReactNode, useId, useState } from "react";

import { ThemePicker } from "@/components/purchasing/theme-picker";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { ROLE_LABELS, type Role, useRole } from "@/lib/role";
import { cn } from "@/lib/utils";

export interface NavItem {
  id: string;
  label: string;
  /** A route path, or `#id` for a link within the page. */
  href: string;
  icon: LucideIcon;
  /** A count shown beside the label, e.g. pending approvals. */
  count?: number;
}

const HOME: NavItem = { id: "home", label: "Home", href: "/", icon: House };
const AUDIT: NavItem = { id: "audit", label: "Audit log", href: "/audit", icon: ScrollText };
const ABOUT: NavItem = { id: "about", label: "About", href: "/about", icon: Info };

export const KITCHEN_NAV: NavItem[] = [
  HOME,
  { id: "requests", label: "Requests", href: "/requests", icon: Inbox },
  { id: "approvals", label: "Approvals", href: "/approvals", icon: UserCheck },
  { id: "orders", label: "Orders", href: "/orders", icon: Package },
  { id: "stock", label: "Stock", href: "/stock", icon: Archive },
  { id: "planner", label: "Planner", href: "/planner", icon: CalendarDays },
  { id: "suppliers", label: "Suppliers", href: "/suppliers", icon: Truck },
  { id: "products", label: "Products", href: "/products", icon: ShoppingBasket },
  { id: "catalog", label: "Catalog", href: "/catalog", icon: BookOpen },
  { id: "settings", label: "Settings", href: "/settings", icon: Settings },
  AUDIT,
  ABOUT,
];

export const VALIO_NAV: NavItem[] = [
  HOME,
  { id: "demand", label: "Demand", href: "/demand", icon: TrendingUp },
  AUDIT,
  ABOUT,
];

/** The kitchen side's items; the kit page builds its own list from these. */
export const NAV_ITEMS = KITCHEN_NAV;

/** `/orders/ORD-1` highlights Orders; Home only matches exactly. */
function activeFromPath(items: NavItem[], pathname: string): string | undefined {
  return items.find((item) =>
    item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`),
  )?.id;
}

function NavList({ items, activeId, onNavigate }: { items: NavItem[]; activeId?: string; onNavigate?: () => void }) {
  return (
    <nav aria-label="Main">
      <ul className="space-y-1">
        {items.map((item) => {
          const active = item.id === activeId;
          const Icon = item.icon;
          const shared = {
            "aria-current": active ? ("page" as const) : undefined,
            onClick: onNavigate,
            className: cn(
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium outline-none hover:bg-accent focus-visible:ring-[3px] focus-visible:ring-ring/70",
              active ? "bg-accent text-accent-foreground" : "text-muted-foreground",
            ),
          };
          const content = (
            <>
              <Icon className="size-4" aria-hidden />
              <span className="flex-1">{item.label}</span>
              {item.count ? (
                <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground tabular-nums">
                  {item.count}
                </span>
              ) : null}
            </>
          );
          return (
            <li key={item.id}>
              {item.href.startsWith("#") ? (
                <a href={item.href} {...shared}>
                  {content}
                </a>
              ) : (
                <Link to={item.href as LinkProps["to"]} {...shared}>
                  {content}
                </Link>
              )}
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** No login: the viewer picks a role, which also picks the side (Kitchen or Valio). */
function RolePicker() {
  const { role, setRole } = useRole();
  const id = useId();
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-xs text-muted-foreground">
        Viewing as
      </Label>
      <Select value={role} onValueChange={(value) => setRole(value as Role)}>
        <SelectTrigger id={id} className="w-full">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {(Object.keys(ROLE_LABELS) as Role[]).map((value) => (
            <SelectItem key={value} value={value}>
              {ROLE_LABELS[value]}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}

/** The theme stays one tap away at the foot of the nav; every display choice is in Settings > Appearance. */
function ShellFooter() {
  return (
    <div className="mt-auto space-y-4 border-t pt-4">
      <ThemePicker />
    </div>
  );
}

function Brand() {
  return (
    <span className="flex items-center gap-2 font-semibold">
      <span className="flex size-8 items-center justify-center rounded-lg bg-primary text-primary-foreground">
        <ChefHat className="size-5" aria-hidden />
      </span>
      Kitchen Buyer
    </span>
  );
}

/**
 * The app frame: a fixed sidebar from `md` up; on a phone a top bar whose
 * menu button opens the same nav in a drawer. Without `items` the nav
 * follows the viewer's side and highlights the current route.
 */
export function AppShell({ items, activeId, children }: { items?: NavItem[]; activeId?: string; children: ReactNode }) {
  const [open, setOpen] = useState(false);
  const { side } = useRole();
  const pathname = useRouterState({ select: (state) => state.location.pathname });
  const nav = items ?? (side === "valio" ? VALIO_NAV : KITCHEN_NAV);
  const current = activeId ?? activeFromPath(nav, pathname);
  return (
    <div className="min-h-screen bg-background md:flex">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col gap-6 overflow-y-auto border-r p-4 md:flex">
        <Brand />
        <RolePicker />
        <NavList items={nav} activeId={current} />
        <ShellFooter />
      </aside>

      <header className="sticky top-0 z-40 flex h-[calc(3.5rem+env(safe-area-inset-top,0px))] items-center gap-3 border-b bg-background/95 pt-[env(safe-area-inset-top,0px)] pr-[calc(1rem+env(safe-area-inset-right,0px))] pl-[calc(1rem+env(safe-area-inset-left,0px))] backdrop-blur md:hidden">
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
          <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-y-auto px-4">
            <RolePicker />
            <NavList items={nav} activeId={current} onNavigate={() => setOpen(false)} />
            <ShellFooter />
          </div>
        </SheetContent>
      </Sheet>

      {/* Safe-area insets are 0px on devices without a notch, so the gutters stay 1rem / 2rem there. */}
      <main className="min-w-0 flex-1 pt-6 pr-[calc(1rem+env(safe-area-inset-right,0px))] pb-[calc(1.5rem+env(safe-area-inset-bottom,0px))] pl-[calc(1rem+env(safe-area-inset-left,0px))] md:pr-[calc(2rem+env(safe-area-inset-right,0px))] md:pl-[calc(2rem+env(safe-area-inset-left,0px))]">
        {children}
      </main>
    </div>
  );
}
