/// <reference types="vitest/config" />
import { fileURLToPath, URL } from "node:url";

import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Dates render in the runner's zone. Valio's server time is Helsinki,
    // so pin it: a test then asserts the same text on every machine.
    env: { TZ: "Europe/Helsinki" },
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
