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
import { ApprovalsPage } from "@/pages/approvals";
import { AuditPage } from "@/pages/audit";
import { CatalogPage } from "@/pages/catalog";
import { DemandPage } from "@/pages/demand";
import { OrderDetailPage } from "@/pages/order-detail";
import { OrdersPage } from "@/pages/orders";
import { PlannerPage } from "@/pages/planner";
import { ProductsPage } from "@/pages/products";
import { RequestsPage } from "@/pages/requests";
import { StockPage } from "@/pages/stock";
import { SuppliersPage } from "@/pages/suppliers";
import { HomePage } from "@/pages/home";
import { DEFAULT_SETTINGS_SECTION } from "@/pages/settings/sections";
import { SettingsPage } from "@/pages/settings/settings-page";

function RootLayout() {
  return (
    <RoleProvider>
      <Outlet />
    </RoleProvider>
  );
}
const rootRoute = createRootRoute({ component: RootLayout });

const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: HomePage });
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
const catalogRoute = createRoute({ getParentRoute: () => rootRoute, path: "/catalog", component: CatalogPage });
const stockRoute = createRoute({ getParentRoute: () => rootRoute, path: "/stock", component: StockPage });
const suppliersRoute = createRoute({ getParentRoute: () => rootRoute, path: "/suppliers", component: SuppliersPage });
const productsRoute = createRoute({ getParentRoute: () => rootRoute, path: "/products", component: ProductsPage });
const plannerRoute = createRoute({ getParentRoute: () => rootRoute, path: "/planner", component: PlannerPage });
const demandRoute = createRoute({ getParentRoute: () => rootRoute, path: "/demand", component: DemandPage });
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

const routeTree = rootRoute.addChildren([
  indexRoute,
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
  settingsRoute,
  settingsSectionRoute,
  aboutRoute,
]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
