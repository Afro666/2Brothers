import { Link, type LinkProps, useRouterState } from "@tanstack/react-router";
import {
  Archive,
  BookOpen,
  CalendarDays,
  ChartLine,
  ChefHat,
  House,
  Inbox,
  Info,
  Menu,
  Package,
  ScrollText,
  Settings,
  ShieldCheck,
  ShoppingBasket,
  TrendingUp,
  Truck,
  UserCheck,
  type LucideIcon,
} from "lucide-react";
import { type ReactNode, useId, useState } from "react";

import type { Api } from "@/api/types";
import { KitchenLogo } from "@/components/purchasing/kitchen-logo";
import { SampleData } from "@/components/purchasing/sample-data";
import { ThemePicker } from "@/components/purchasing/theme-picker";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { usePendingApprovals } from "@/lib/pending-approvals";
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
  /** The heading this item sits under; items without one come first. */
  group?: string;
  /** A small link in the row at the foot of the menu. */
  foot?: boolean;
}

const HOME: NavItem = { id: "home", label: "Home", href: "/", icon: House };
const AUDIT: NavItem = { id: "audit", label: "Activity log", href: "/audit", icon: ScrollText, group: "Reports" };
const ABOUT: NavItem = { id: "about", label: "About", href: "/about", icon: Info, foot: true };

// Five menu entries instead of thirteen: pages that belong together share one entry and show as tabs
// at the top of the page. Labels were checked with a first-time reader; keep them saying what the page is for.
export const KITCHEN_NAV: NavItem[] = [
  HOME,
  { id: "requests", label: "Request an order", href: "/requests", icon: Inbox, group: "Orders" },
  { id: "approvals", label: "To approve", href: "/approvals", icon: UserCheck, group: "Orders" },
  { id: "orders", label: "Order history", href: "/orders", icon: Package, group: "Orders" },
  { id: "planner", label: "Menu plan", href: "/planner", icon: CalendarDays, group: "Kitchen" },
  { id: "stock", label: "Stock count", href: "/stock", icon: Archive, group: "Kitchen" },
  { id: "products", label: "Recipes", href: "/products", icon: ShoppingBasket, group: "Kitchen" },
  { id: "catalog", label: "Products", href: "/catalog", icon: BookOpen, group: "Catalog" },
  { id: "suppliers", label: "Suppliers", href: "/suppliers", icon: Truck, group: "Catalog" },
  { id: "forecast", label: "Forecast vs actual", href: "/forecast", icon: ChartLine, group: "Reports" },
  AUDIT,
  { id: "trust", label: "Tamper check", href: "/trust", icon: ShieldCheck, group: "Reports" },
  { id: "settings", label: "Settings", href: "/settings", icon: Settings, foot: true },
  ABOUT,
];

export const VALIO_NAV: NavItem[] = [
  HOME,
  { id: "demand", label: "Demand", href: "/demand", icon: TrendingUp },
  { ...AUDIT, group: undefined },
  ABOUT,
];

const GROUP_ICONS: Record<string, LucideIcon> = {
  Orders: Package,
  Kitchen: CalendarDays,
  Catalog: BookOpen,
  Reports: ChartLine,
};

const groupId = (group: string) => `group:${group}`;

/** The menu's entries: each group becomes one entry that opens the group's first page. */
function menuEntries(items: NavItem[]): NavItem[] {
  const entries: NavItem[] = [];
  for (const item of items) {
    if (!item.group) {
      entries.push(item);
      continue;
    }
    const entry = entries.find((other) => other.id === groupId(item.group!));
    if (entry) entry.count = (entry.count ?? 0) + (item.count ?? 0) || undefined;
    else
      entries.push({
        id: groupId(item.group),
        label: item.group,
        href: item.href,
        icon: GROUP_ICONS[item.group] ?? item.icon,
        count: item.count,
      });
  }
  return entries;
}

/** The method each screen's own data comes from: in gateway mode the screen is marked while that is still the mock. */
const SCREEN_DATA: Record<string, keyof Api> = {
  stock: "getStock",
  planner: "getMenuPlan",
  forecast: "getForecastAccuracy",
  suppliers: "listSuppliers",
  products: "listOwnProducts",
  catalog: "searchProducts",
  demand: "getSupplierDemand",
};

/** The kitchen side's items; the kit page builds its own list from these. */
export const NAV_ITEMS = KITCHEN_NAV;

/** `/orders/ORD-1` highlights Orders; Home only matches exactly. */
function activeFromPath(items: NavItem[], pathname: string): string | undefined {
  return items.find((item) =>
    item.href === "/" ? pathname === "/" : pathname === item.href || pathname.startsWith(`${item.href}/`),
  )?.id;
}

function NavLink({ item, active, onNavigate }: { item: NavItem; active: boolean; onNavigate?: () => void }) {
  const Icon = item.icon;
  const shared = {
    "aria-current": active ? ("page" as const) : undefined,
    // The count is in the description, so the link keeps its plain name.
    "aria-description": item.count ? `${item.count} waiting` : undefined,
    onClick: onNavigate,
    className: cn(
      "flex items-center gap-2 rounded-sm border-l-2 font-medium outline-none hover:bg-muted hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/70",
      item.foot ? "px-2 py-1.5 text-xs" : "px-3 py-2 text-sm",
      active ? "border-primary bg-accent text-foreground" : "border-transparent text-muted-foreground",
    ),
  };
  const content = (
    <>
      <Icon className={item.foot ? "size-3.5" : "size-4"} aria-hidden />
      <span className="flex-1">{item.label}</span>
      {item.count ? (
        <span aria-hidden data-nav-count className="rounded-sm bg-foreground px-1.5 font-mono text-[11px] text-background">
          {item.count}
        </span>
      ) : null}
    </>
  );
  return item.href.startsWith("#") ? (
    <a href={item.href} {...shared}>
      {content}
    </a>
  ) : (
    <Link to={item.href as LinkProps["to"]} {...shared}>
      {content}
    </Link>
  );
}

/** The main entries as a list, then the small foot links in one row at the bottom. */
function NavList({ items, activeId, onNavigate }: { items: NavItem[]; activeId?: string; onNavigate?: () => void }) {
  const main = items.filter((item) => !item.foot);
  const foot = items.filter((item) => item.foot);
  return (
    <nav aria-label="Main" className="flex flex-1 flex-col gap-4">
      <ul className="space-y-1">
        {main.map((item) => (
          <li key={item.id}>
            <NavLink item={item} active={item.id === activeId} onNavigate={onNavigate} />
          </li>
        ))}
      </ul>
      {foot.length ? (
        <ul className="mt-auto flex flex-wrap gap-1 border-t pt-3">
          {foot.map((item) => (
            <li key={item.id}>
              <NavLink item={item} active={item.id === activeId} onNavigate={onNavigate} />
            </li>
          ))}
        </ul>
      ) : null}
    </nav>
  );
}

/** The pages of the current menu entry, as tabs above the page. */
function SectionTabs({ label, items, activeId }: { label: string; items: NavItem[]; activeId?: string }) {
  return (
    <nav aria-label={label} className="mb-6 overflow-x-auto">
      <ul className="flex gap-1 border-b">
        {items.map((item) => {
          const active = item.id === activeId;
          return (
            <li key={item.id}>
              <Link
                to={item.href as LinkProps["to"]}
                aria-current={active ? "page" : undefined}
                aria-description={item.count ? `${item.count} waiting` : undefined}
                className={cn(
                  "-mb-px flex items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium whitespace-nowrap outline-none hover:text-foreground focus-visible:ring-[3px] focus-visible:ring-ring/70",
                  active ? "border-foreground text-foreground" : "border-transparent text-muted-foreground",
                )}
              >
                {item.label}
                {item.count ? (
                  <span aria-hidden data-nav-count className="rounded-sm bg-foreground px-1.5 font-mono text-[11px] text-background">
                    {item.count}
                  </span>
                ) : null}
              </Link>
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
      <Label htmlFor={id} className="label-caps">
        Your role
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
    <div className="space-y-4">
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
      <span className="stamp text-[15px]">Kitchen Buyer</span>
      <KitchenLogo />
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
  const { count: waiting } = usePendingApprovals();
  const base = items ?? (side === "valio" ? VALIO_NAV : KITCHEN_NAV);
  // Only the kitchen's own menu shows what waits; zero or unknown shows no badge.
  const nav =
    !items && side === "kitchen" && waiting
      ? base.map((item) => (item.id === "approvals" ? { ...item, count: waiting } : item))
      : base;
  const current = activeId ?? activeFromPath(nav, pathname);
  const group = nav.find((item) => item.id === current)?.group;
  const tabs = group ? nav.filter((item) => item.group === group) : [];
  const menu = menuEntries(nav);
  const menuActive = group ? groupId(group) : current;
  return (
    <div className="min-h-screen bg-background md:flex">
      <aside className="sticky top-0 hidden h-screen w-56 shrink-0 flex-col gap-5 overflow-y-auto border-r p-4 md:flex">
        <Brand />
        <RolePicker />
        <NavList items={menu} activeId={menuActive} />
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
            <NavList items={menu} activeId={menuActive} onNavigate={() => setOpen(false)} />
            <ShellFooter />
          </div>
        </SheetContent>
      </Sheet>

      {/* Safe-area insets are 0px on devices without a notch, so the gutters stay 1rem / 2rem there. */}
      <main className="min-w-0 flex-1 pt-6 pr-[calc(1rem+env(safe-area-inset-right,0px))] pb-[calc(1.5rem+env(safe-area-inset-bottom,0px))] pl-[calc(1rem+env(safe-area-inset-left,0px))] md:pr-[calc(2rem+env(safe-area-inset-right,0px))] md:pl-[calc(2rem+env(safe-area-inset-left,0px))]">
        {group && tabs.length > 1 ? <SectionTabs label={group} items={tabs} activeId={current} /> : null}
        {current && SCREEN_DATA[current] ? (
          <div className="mx-auto mb-3 max-w-5xl empty:hidden">
            <SampleData of={SCREEN_DATA[current]} />
          </div>
        ) : null}
        {children}
      </main>
    </div>
  );
}
