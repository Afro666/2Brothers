import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiProvider } from "@/api";
import { ThemeProvider } from "@/lib/theme";
import { createAppRouter } from "@/router";

import "./index.css";

const router = createAppRouter();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <ApiProvider>
        <TooltipProvider>
          <RouterProvider router={router} />
          <Toaster />
        </TooltipProvider>
      </ApiProvider>
    </ThemeProvider>
  </StrictMode>,
);
