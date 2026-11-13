import { RouterProvider } from "@tanstack/react-router";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";

import { TooltipProvider } from "@/components/ui/tooltip";
import { ApiProvider } from "@/api";
import { createAppRouter } from "@/router";

import "./index.css";

const router = createAppRouter();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ApiProvider>
      <TooltipProvider>
        <RouterProvider router={router} />
        <Toaster position="bottom-right" theme="system" richColors />
      </TooltipProvider>
    </ApiProvider>
  </StrictMode>,
);
