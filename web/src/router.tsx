import { type RouterHistory, Outlet, createRootRoute, createRoute, createRouter } from "@tanstack/react-router";

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
]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
