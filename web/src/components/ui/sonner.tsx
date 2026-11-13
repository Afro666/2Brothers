import { Toaster as Sonner } from "sonner";

import { useTheme } from "@/lib/theme";

/** The one app toaster. It follows the chosen theme, which can differ from the device setting. */
export function Toaster() {
  const { resolved } = useTheme();
  return <Sonner position="bottom-right" theme={resolved} richColors />;
}
