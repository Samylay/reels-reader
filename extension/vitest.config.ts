import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node", // tests import jsdom directly, not via vitest env
    include: ["test/**/*.test.ts"],
  },
});
