import { createLucideIcon } from "lucide-react";

/** Product shapes missing from Lucide, using its 24 px outline style. */
export const Potato = createLucideIcon({
  name: "Potato",
  node: [
    ["path", {
      d: "M12.5 4.25C16.9 4.05 20.1 6.9 20.45 10.9C20.8 14.9 19.1 18.1 15.8 19.35C13.2 20.35 10.2 20.2 7.7 19.05C4.9 17.75 3.35 15.2 3.55 12.15C3.75 9.1 5.55 6.55 8.35 5.35C9.65 4.8 11.05 4.4 12.5 4.25Z",
    }],
    ["path", { d: "m9 9 .5-.5m5 6 .5-.5m1-6 .5.5" }],
  ],
});
