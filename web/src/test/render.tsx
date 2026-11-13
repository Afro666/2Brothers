import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render } from "@testing-library/react";

import { type Api, ApiProvider } from "@/api";
import { createMockApi } from "@/api/mock";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ThemeProvider } from "@/lib/theme";
import { createAppRouter } from "@/router";

/** Renders the whole app at a path, with a fresh mock API unless one is given. */
export function renderApp(path: string, api: Api = createMockApi()) {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  render(
    <ThemeProvider>
      <ApiProvider api={api}>
        <TooltipProvider>
          <RouterProvider router={router} />
          <Toaster />
        </TooltipProvider>
      </ApiProvider>
    </ThemeProvider>,
  );
  return { api, router };
}
