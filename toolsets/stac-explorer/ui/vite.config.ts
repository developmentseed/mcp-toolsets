import { resolve } from "node:path";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { viteSingleFile } from "vite-plugin-singlefile";

// Each view builds to a single self-contained file (all JS/CSS inlined)
// written straight into the Python package's views/ dir, where the runtime
// serves it as the ui://stac-explorer/<view> resource. viteSingleFile inlines
// dynamic imports, which forbids multiple inputs in one build — so we build one
// view per pass, selected by the VIEW env var (see package.json's build script;
// keep the names in sync with VIEWS in stac_explorer/tools.py).
const view = process.env.VIEW;
if (!view) {
  throw new Error("set VIEW=<view-id> (e.g. VIEW=map vite build)");
}

export default defineConfig({
  plugins: [react(), viteSingleFile()],
  build: {
    outDir: resolve(__dirname, "../src/stac_explorer/views"),
    emptyOutDir: false,
    rollupOptions: {
      input: { [view]: resolve(__dirname, `${view}.html`) },
    },
  },
});
