import {
  type RouterHistory,
  Link,
  Outlet,
  createRootRoute,
  createRoute,
  createRouter,
} from "@tanstack/react-router";

import { KitPage } from "@/pages/kit";

const rootRoute = createRootRoute({ component: Outlet });

function HomePage() {
  return (
    <main className="mx-auto max-w-prose space-y-3 px-4 py-12">
      <h1 className="text-2xl font-semibold">Kitchen Buyer</h1>
      <p className="text-muted-foreground">
        The real screens come next. The component kit shows every purchasing component with mock data.
      </p>
      <Link to="/kit" className="font-medium underline underline-offset-4">
        Open the component kit
      </Link>
    </main>
  );
}

const indexRoute = createRoute({ getParentRoute: () => rootRoute, path: "/", component: HomePage });
const kitRoute = createRoute({ getParentRoute: () => rootRoute, path: "/kit", component: KitPage });

const routeTree = rootRoute.addChildren([indexRoute, kitRoute]);

export function createAppRouter(history?: RouterHistory) {
  return createRouter({ routeTree, history });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof createAppRouter>;
  }
}
