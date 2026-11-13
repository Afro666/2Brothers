import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { render } from "@testing-library/react";
import { Toaster } from "sonner";

import { type Api, ApiProvider } from "@/api";
import { createMockApi } from "@/api/mock";
import { TooltipProvider } from "@/components/ui/tooltip";
import { createAppRouter } from "@/router";

/** Renders the whole app at a path, with a fresh mock API unless one is given. */
export function renderApp(path: string, api: Api = createMockApi()) {
  if (typeof window.matchMedia !== "function") {
    window.matchMedia = (media) =>
      ({
        matches: false,
        media,
        onchange: null,
        addListener: () => undefined,
        removeListener: () => undefined,
        addEventListener: () => undefined,
        removeEventListener: () => undefined,
        dispatchEvent: () => false,
      }) as MediaQueryList;
  }
  const router = createAppRouter(createMemoryHistory({ initialEntries: [path] }));
  render(
    <ApiProvider api={api}>
      <TooltipProvider>
        <RouterProvider router={router} />
        <Toaster position="bottom-right" theme="system" richColors />
      </TooltipProvider>
    </ApiProvider>,
  );
  return { api, router };
}
