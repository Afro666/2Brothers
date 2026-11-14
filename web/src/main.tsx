import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiProvider } from "@/api";
import { PendingApprovalsProvider } from "@/lib/pending-approvals";
import { ThemeProvider } from "@/lib/theme";
import { createAppRouter } from "@/router";

import "@fontsource-variable/atkinson-hyperlegible-next";
import "@fontsource-variable/atkinson-hyperlegible-mono";
import "@fontsource-variable/archivo/standard.css";
import "./index.css";

const router = createAppRouter();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <ApiProvider>
        <PendingApprovalsProvider>
          <TooltipProvider>
            <RouterProvider router={router} />
            <Toaster />
          </TooltipProvider>
        </PendingApprovalsProvider>
      </ApiProvider>
    </ThemeProvider>
  </StrictMode>,
);
