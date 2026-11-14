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

export const Butter = createLucideIcon({
  name: "Butter",
  node: [
    ["path", { d: "M7 5h10a3 3 0 0 1 3 3v9H4V8a3 3 0 0 1 3-3Z" }],
    ["path", { d: "M8 5v12" }],
    ["path", { d: "M2 17h20c-1 2-3 3-5 3H7c-2 0-4-1-5-3Z" }],
  ],
});

export const Mushroom = createLucideIcon({
  name: "Mushroom",
  node: [
    ["path", { d: "M3 12a9 9 0 0 1 18 0Z" }],
    ["path", { d: "M9 12v5a3 3 0 0 0 6 0v-5Z" }],
  ],
});

export const Onion = createLucideIcon({
  name: "Onion",
  node: [
    ["path", { d: "M12 3c-1 3-7 5-7 10a7 7 0 0 0 14 0c0-5-6-7-7-10Z" }],
    ["path", { d: "M12 7c-2 3-3 5-3 8a6 6 0 0 0 3 5" }],
    ["path", { d: "M12 7c2 3 3 5 3 8a6 6 0 0 1-3 5" }],
    ["path", { d: "m9 20-1 2m4-2v2m3-2 1 2" }],
  ],
});

export const Cucumber = createLucideIcon({
  name: "Cucumber",
  node: [
    ["path", { d: "M7 3C4 3 3 4 3 7c0 2 1 4 3 6l5 5c2 2 4 3 6 3 3 0 4-1 4-4 0-2-1-4-3-6l-5-5C11 4 9 3 7 3Z" }],
    ["path", { d: "m6 8 1-1m3 5 1-1m4 4 1-1" }],
  ],
});

export const Tomato = createLucideIcon({
  name: "Tomato",
  node: [
    ["path", { d: "M12 5C7 3 3 7 3 12a9 9 0 0 0 18 0c0-5-4-9-9-7Z" }],
    ["path", { d: "m12 2 1 3h3l-2 2 1 3-3-2-3 2 1-3-2-2h3Z" }],
  ],
});

export const Pepper = createLucideIcon({
  name: "Pepper",
  node: [
    ["path", { d: "M10 7C7 5 4 7 4 11c0 5 2 9 5 9 1 0 2-1 3-1s2 1 3 1c3 0 5-4 5-9 0-4-3-6-6-4l-2 1Z" }],
    ["path", { d: "M10 8c-1 5 0 9 2 11m4-11c1 5 0 9-2 11" }],
    ["path", { d: "M12 8V5c0-2 1-3 3-3" }],
  ],
});

export const Beet = createLucideIcon({
  name: "Beet",
  node: [
    ["path", { d: "M12 8c-5 0-8 2-8 6s3 6 8 6 8-2 8-6-3-6-8-6Zm0 12 1 2" }],
    ["path", { d: "M12 9C8 8 6 5 6 2c4 0 6 3 6 7Z" }],
    ["path", { d: "M12 8c0-4 2-6 6-6 0 4-2 6-6 6Z" }],
  ],
});
