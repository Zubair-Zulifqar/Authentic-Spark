import { defineConfig } from "@playwright/test";

// Requires the API (port 8080, seeded, AUTH_MODE=dev) and web app (port 3000) to be running.
export default defineConfig({
  testDir: "./e2e",
  use: { baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000" },
});
