import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render } from "@testing-library/react";

import { type Api, ApiProvider } from "@/api";
import { createMockApi } from "@/api/mock";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { PendingApprovalsProvider } from "@/lib/pending-approvals";
import { ThemeProvider } from "@/lib/theme";
import { createAppRouter } from "@/router";

/** Renders the whole app at a path, with a fresh mock API unless one is given. */
export function renderApp(path: string, api: Api = createMockApi()) {
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  render(
    <ThemeProvider>
      <ApiProvider api={api}>
        <PendingApprovalsProvider>
          <TooltipProvider>
            <RouterProvider router={router} />
            <Toaster />
          </TooltipProvider>
        </PendingApprovalsProvider>
      </ApiProvider>
    </ThemeProvider>,
  );
  return { api, router };
}
