import { fileURLToPath } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      // Mirrors tsconfig `paths`: components import `@/components/...` and
      // `@/src/lib/api/...`, so the test runner must resolve the same root.
      "@": fileURLToPath(new URL("./", import.meta.url)),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    // Tests opt into globals explicitly (`import { describe } from "vitest"`)
    // so eslint and tsc do not need a second global type surface.
    globals: false,
    css: false,
  },
});