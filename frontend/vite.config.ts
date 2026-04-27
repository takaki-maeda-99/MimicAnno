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
        const sirvHandler = sirv(runsDir, { dev: true, etag: true });
        server.middlewares.use("/runs", (req, res, next) => {
          sirvHandler(req, res, () => {
            // sirv did not find the file. Don't fall through to Vite's
            // SPA history fallback (which would serve index.html and
            // mask the missing artifact). Spec §5 contract: missing
            // artifact must surface as HTTP 404 so RunViewer can render
            // `failed to load <role>: HTTP 404`.
            res.statusCode = 404;
            res.end(`Not found: ${req.url}`);
            // Suppress the unused next param.
            void next;
          });
        });
      },
    },
  ],
  server: {
    fs: { allow: [repoRoot] },
  },
});
