import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // Phase 5 B r1 T11.5: switched from "node" so React + Testing
    // Library can render into a DOM. Existing pure-logic tests
    // (fetchRetry, manifest, runSelection, time) don't touch globals so
    // jsdom is a no-op for them; component tests in T13+ need it.
    environment: "jsdom",
    // .tsx required for React component tests added in T13/T14.
    include: ["src/**/__tests__/**/*.test.{ts,tsx}"],
    passWithNoTests: true,
  },
});
