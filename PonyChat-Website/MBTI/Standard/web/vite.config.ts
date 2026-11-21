import path from "node:path";
import { fileURLToPath } from "node:url";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(__dirname, "../..");
const nm = path.resolve(__dirname, "node_modules");

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@common": path.resolve(__dirname, "../../Common/src"),
      "@data": path.resolve(__dirname, "./src/data"),
      react: path.join(nm, "react"),
      "react-dom": path.join(nm, "react-dom"),
      "react-router-dom": path.join(nm, "react-router-dom"),
    },
  },
  server: {
    fs: {
      allow: [repoRoot],
    },
  },
});
