import {
  type RouterHistory,
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
  redirect,
} from "@tanstack/react-router";

import { AboutPage } from "@/pages/about";
import { KitPage } from "@/pages/kit";
import { RoleProvider } from "@/lib/role";
import { SessionProvider } from "@/lib/session";
import { ApprovalsPage } from "@/pages/approvals";
import { AuditPage } from "@/pages/audit";
import { CatalogPage, validateCatalogSearch } from "@/pages/catalog";
import { DemandPage } from "@/pages/demand";
import { ForecastPage } from "@/pages/forecast";
import { OrderDetailPage } from "@/pages/order-detail";
import { OrdersPage } from "@/pages/orders";
import { OnboardingPage } from "@/pages/onboarding";
import { PlannerPage } from "@/pages/planner";
import { ProductsPage } from "@/pages/products";
import { RequestsPage } from "@/pages/requests";
import { StockPage } from "@/pages/stock";
import { SuppliersPage } from "@/pages/suppliers";
import { HomePage } from "@/pages/home";
import { DEFAULT_SETTINGS_SECTION } from "@/pages/settings/sections";
import { SettingsPage } from "@/pages/settings/settings-page";
import { TrustPage } from "@/pages/trust";
import { SignInPage } from "@/pages/sign-in";

function RootLayout() {
  return (
    <SessionProvider>
      <RoleProvider>
        <Outlet />
      </RoleProvider>
    </SessionProvider>
  );
}
const rootRoute = createRootRoute({ component: RootLayout });

const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: HomePage });
const signInRoute = createRoute({ getParentRoute: () => rootRoute, path: "/sign-in", component: SignInPage });
const kitRoute = createRoute({ getParentRoute: () => rootRoute, path: "/kit", component: KitPage });
const requestsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/requests", component: RequestsPage });
const approvalsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/approvals", component: ApprovalsPage });
const ordersRoute = createRoute({ getParentRoute: () => rootRoute, path: "/orders", component: OrdersPage });
const orderDetailRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/orders/$orderId",
  component: OrderDetailPage,
});
const auditRoute = createRoute({ getParentRoute: () => rootRoute, path: "/audit", component: AuditPage });
const catalogRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/catalog",
  validateSearch: validateCatalogSearch,
  component: CatalogPage,
});
const stockRoute = createRoute({ getParentRoute: () => rootRoute, path: "/stock", component: StockPage });
const suppliersRoute = createRoute({ getParentRoute: () => rootRoute, path: "/suppliers", component: SuppliersPage });
const productsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/products", component: ProductsPage });
const plannerRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/planner",
  // Keep `week` only when it is an ISO week such as 2026-W47; otherwise the planner opens on next week.
  validateSearch: (search: Record<string, unknown>): { week?: string } => ({
    week: typeof search.week === "string" && /^\d{4}-W\d{2}$/.test(search.week) ? search.week : undefined,
  }),
  component: PlannerPage,
});
const demandRoute = createRoute({ getParentRoute: () => rootRoute, path: "/demand", component: DemandPage });
const forecastRoute = createRoute({ getParentRoute: () => rootRoute, path: "/forecast", component: ForecastPage });
const settingsRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings",
  // A phone gets the section list alone; a wider screen has room for a section beside it.
  beforeLoad: () => {
    if (typeof window.matchMedia === "function" && window.matchMedia("(min-width: 768px)").matches) {
      throw redirect({ to: "/settings/$section", params: { section: DEFAULT_SETTINGS_SECTION }, replace: true });
    }
  },
  component: SettingsPage,
});
// One route for every section: the list in pages/settings/sections.ts decides what `$section` shows.
const settingsSectionRoute = createRoute({
  getParentRoute: () => rootRoute,
  path: "/settings/$section",
  component: SettingsPage,
});
const aboutRoute = createRoute({ getParentRoute: () => rootRoute, path: "/about", component: AboutPage });
const trustRoute = createRoute({ getParentRoute: () => rootRoute, path: "/trust", component: TrustPage });
const onboardingRoute = createRoute({ getParentRoute: () => rootRoute, path: "/onboarding", component: OnboardingPage });

const routeTree = rootRoute.addChildren([
  indexRoute,
  signInRoute,
  kitRoute,
  requestsRoute,
  approvalsRoute,
  ordersRoute,
  orderDetailRoute,
  auditRoute,
  catalogRoute,
  stockRoute,
  suppliersRoute,
  productsRoute,
  plannerRoute,
  demandRoute,
  forecastRoute,
  settingsRoute,
  settingsSectionRoute,
  aboutRoute,
  trustRoute,
  onboardingRoute,
]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
