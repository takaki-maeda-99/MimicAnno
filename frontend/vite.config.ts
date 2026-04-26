import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";
import sirv from "sirv";

const repoRoot = path.resolve(__dirname, "..");
const runsDir = path.resolve(repoRoot, "runs");

export default defineConfig({
  plugins: [
    react(),
    {
      name: "serve-runs",
      configureServer(server) {
        server.middlewares.use("/runs", sirv(runsDir, { dev: true, etag: true }));
      },
    },
  ],
  server: {
    fs: { allow: [repoRoot] },
  },
});
